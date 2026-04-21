import asyncio
import json
import os
import time
from engine.runner import BenchmarkRunner
from engine.llm_judge import LLMJudge
from engine.retrieval_eval import RetrievalEvaluator
from agent.main_agent import MainAgent, OptimizedAgent

RELEASE_THRESHOLDS = {
    "min_avg_score": 3.5,
    "max_score_regression": -0.5,
    "min_hit_rate": 0.7,
    "max_cost_increase_pct": 30,
    "max_latency_increase_pct": 50,
}


def release_gate(v1_metrics: dict, v2_metrics: dict) -> dict:
    """
    Automatic Release Gate: decides APPROVE, CONDITIONAL, or BLOCK
    based on configurable quality/cost/latency thresholds.
    """
    checks = []

    v2_score = v2_metrics.get("avg_score", 0)
    checks.append({
        "check": "min_avg_score",
        "threshold": RELEASE_THRESHOLDS["min_avg_score"],
        "value": v2_score,
        "passed": v2_score >= RELEASE_THRESHOLDS["min_avg_score"],
    })

    score_delta = v2_score - v1_metrics.get("avg_score", 0)
    checks.append({
        "check": "score_regression",
        "threshold": RELEASE_THRESHOLDS["max_score_regression"],
        "value": score_delta,
        "passed": score_delta >= RELEASE_THRESHOLDS["max_score_regression"],
    })

    v2_hr = v2_metrics.get("hit_rate", 0)
    checks.append({
        "check": "min_hit_rate",
        "threshold": RELEASE_THRESHOLDS["min_hit_rate"],
        "value": v2_hr,
        "passed": v2_hr >= RELEASE_THRESHOLDS["min_hit_rate"],
    })

    v1_cost = v1_metrics.get("total_cost_usd", 0.001)
    v2_cost = v2_metrics.get("total_cost_usd", 0)
    cost_increase = ((v2_cost - v1_cost) / v1_cost * 100) if v1_cost > 0 else 0
    checks.append({
        "check": "cost_increase",
        "threshold": f"{RELEASE_THRESHOLDS['max_cost_increase_pct']}%",
        "value": f"{cost_increase:.1f}%",
        "passed": cost_increase <= RELEASE_THRESHOLDS["max_cost_increase_pct"],
    })

    v1_lat = v1_metrics.get("avg_latency", 0.001)
    v2_lat = v2_metrics.get("avg_latency", 0)
    lat_increase = ((v2_lat - v1_lat) / v1_lat * 100) if v1_lat > 0 else 0
    checks.append({
        "check": "latency_increase",
        "threshold": f"{RELEASE_THRESHOLDS['max_latency_increase_pct']}%",
        "value": f"{lat_increase:.1f}%",
        "passed": lat_increase <= RELEASE_THRESHOLDS["max_latency_increase_pct"],
    })

    failed = [c for c in checks if not c["passed"]]
    passed = [c for c in checks if c["passed"]]

    if len(failed) == 0:
        decision = "APPROVE"
    elif len(failed) <= 2 and all(c["check"] not in ("min_avg_score", "score_regression") for c in failed):
        decision = "CONDITIONAL"
    else:
        decision = "BLOCK"

    return {
        "decision": decision,
        "checks": checks,
        "passed_count": len(passed),
        "failed_count": len(failed),
        "failed_checks": [c["check"] for c in failed],
    }


def compute_summary(results: list, version: str, perf_report: dict, judge: LLMJudge) -> dict:
    """Build summary dict from benchmark results."""
    total = len(results)
    if total == 0:
        return {"metadata": {"version": version, "total": 0}, "metrics": {}}

    avg_score = sum(r["judge"]["final_score"] for r in results) / total
    avg_agreement = sum(r["judge"]["agreement_rate"] for r in results) / total
    hit_rate = sum(r["ragas"]["retrieval"]["hit_rate"] for r in results) / total
    mrr = sum(r["ragas"]["retrieval"]["mrr"] for r in results) / total
    pass_count = sum(1 for r in results if r["status"] == "pass")
    avg_latency = sum(r["latency"] for r in results) / total

    judge_cost = judge.get_cost_report()
    cohens_kappa = judge.get_cohens_kappa()

    return {
        "metadata": {
            "version": version,
            "total": total,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "metrics": {
            "avg_score": round(avg_score, 3),
            "hit_rate": round(hit_rate, 4),
            "mrr": round(mrr, 4),
            "agreement_rate": round(avg_agreement, 3),
            "cohens_kappa": round(cohens_kappa, 3),
            "pass_rate": round(pass_count / total, 3),
            "avg_latency": round(avg_latency, 3),
            "total_cost_usd": round(judge_cost.get("total_cost_usd", 0), 6),
        },
        "performance": perf_report,
    }


def generate_failure_report(results: list) -> dict:
    """Cluster failures and prepare data for failure analysis."""
    failures = [r for r in results if r["status"] == "fail"]

    clusters = {}
    for f in failures:
        score = f["judge"]["final_score"]
        hit = f["ragas"]["retrieval"]["hit_rate"]
        meta = f.get("metadata", {})

        if hit == 0.0:
            cluster = "Retrieval Failure"
        elif score < 2:
            cluster = "Hallucination"
        elif meta.get("type") == "adversarial" and score < 3:
            cluster = "Safety Violation"
        elif score < 3:
            cluster = "Incomplete/Low Quality"
        else:
            cluster = "Other"

        if cluster not in clusters:
            clusters[cluster] = []
        clusters[cluster].append({
            "question": f["test_case"],
            "score": score,
            "hit_rate": hit,
            "category": meta.get("category", "unknown"),
        })

    sorted_failures = sorted(failures, key=lambda x: x["judge"]["final_score"])
    worst_3 = sorted_failures[:3] if len(sorted_failures) >= 3 else sorted_failures

    return {
        "total_failures": len(failures),
        "total_cases": len(results),
        "failure_rate": round(len(failures) / max(len(results), 1), 3),
        "clusters": {k: {"count": len(v), "cases": v} for k, v in clusters.items()},
        "worst_cases": [{
            "question": w["test_case"],
            "response": w["agent_response"][:200],
            "score": w["judge"]["final_score"],
            "hit_rate": w["ragas"]["retrieval"]["hit_rate"],
        } for w in worst_3],
    }


async def run_benchmark_for_version(agent, dataset: list, version: str):
    """Run full benchmark pipeline for a given agent version."""
    judge = LLMJudge()
    evaluator_placeholder = type("Eval", (), {"score": staticmethod(lambda c, r: {})})()
    runner = BenchmarkRunner(agent, evaluator_placeholder, judge, concurrency=10)

    results = await runner.run_all(dataset)
    perf_report = runner.get_performance_report(results)
    summary = compute_summary(results, version, perf_report, judge)

    retrieval_results = []
    judge_scores = []
    for r in results:
        retrieval_results.append(r["ragas"]["retrieval"])
        judge_scores.append(r["judge"]["final_score"])
    correlation = RetrievalEvaluator.correlate_retrieval_with_quality(retrieval_results, judge_scores)
    summary["retrieval_correlation"] = correlation

    return results, summary, judge


async def main():
    if not os.path.exists("data/golden_set.jsonl"):
        print("Missing data/golden_set.jsonl. Run 'python data/synthetic_gen.py' first.")
        return

    with open("data/golden_set.jsonl", "r", encoding="utf-8") as f:
        dataset = [json.loads(line) for line in f if line.strip()]

    if not dataset:
        print("data/golden_set.jsonl is empty.")
        return

    print(f"Loaded {len(dataset)} test cases from golden set.\n")

    # --- V1 Benchmark ---
    print("=" * 60)
    print("  PHASE 1: Running V1 (Baseline Agent)")
    print("=" * 60)
    v1_agent = MainAgent(version="v1", noise_level=0.20)
    v1_results, v1_summary, _ = await run_benchmark_for_version(v1_agent, dataset, "Agent_V1_Base")

    # --- V2 Benchmark ---
    print("\n" + "=" * 60)
    print("  PHASE 2: Running V2 (Optimized Agent)")
    print("=" * 60)
    v2_agent = OptimizedAgent()
    v2_results, v2_summary, _ = await run_benchmark_for_version(v2_agent, dataset, "Agent_V2_Optimized")

    # --- Regression Analysis ---
    print("\n" + "=" * 60)
    print("  PHASE 3: Regression Analysis & Release Gate")
    print("=" * 60)

    v1_m = v1_summary["metrics"]
    v2_m = v2_summary["metrics"]

    deltas = {}
    for key in v1_m:
        if isinstance(v1_m[key], (int, float)) and isinstance(v2_m.get(key), (int, float)):
            deltas[key] = round(v2_m[key] - v1_m[key], 4)

    gate_result = release_gate(v1_m, v2_m)

    print(f"\n  V1 Avg Score: {v1_m['avg_score']:.3f}  |  V2 Avg Score: {v2_m['avg_score']:.3f}  |  Delta: {deltas.get('avg_score', 0):+.3f}")
    print(f"  V1 Hit Rate:  {v1_m['hit_rate']:.3f}  |  V2 Hit Rate:  {v2_m['hit_rate']:.3f}  |  Delta: {deltas.get('hit_rate', 0):+.4f}")
    print(f"  V1 MRR:       {v1_m['mrr']:.3f}  |  V2 MRR:       {v2_m['mrr']:.3f}  |  Delta: {deltas.get('mrr', 0):+.4f}")
    print(f"  V1 Agreement: {v1_m['agreement_rate']:.3f}  |  V2 Agreement: {v2_m['agreement_rate']:.3f}")
    print(f"  V1 Kappa:     {v1_m['cohens_kappa']:.3f}  |  V2 Kappa:     {v2_m['cohens_kappa']:.3f}")

    print(f"\n  Release Gate Checks:")
    for check in gate_result["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"    [{status}] {check['check']}: value={check['value']}, threshold={check['threshold']}")

    decision = gate_result["decision"]
    if decision == "APPROVE":
        print(f"\n  DECISION: APPROVE - V2 meets all quality thresholds.")
    elif decision == "CONDITIONAL":
        print(f"\n  DECISION: CONDITIONAL - Minor issues: {gate_result['failed_checks']}")
    else:
        print(f"\n  DECISION: BLOCK RELEASE - Failed: {gate_result['failed_checks']}")

    # --- Failure Analysis ---
    failure_report = generate_failure_report(v2_results)

    # --- Save Reports ---
    os.makedirs("reports", exist_ok=True)

    final_summary = {
        **v2_summary,
        "regression": {
            "v1": v1_summary["metrics"],
            "v2": v2_summary["metrics"],
            "deltas": deltas,
            "release_gate": gate_result,
        },
        "failure_analysis": failure_report,
        "retrieval_correlation": v2_summary.get("retrieval_correlation", {}),
    }

    with open("reports/summary.json", "w", encoding="utf-8") as f:
        json.dump(final_summary, f, ensure_ascii=False, indent=2)
    print("\nSaved: reports/summary.json")

    with open("reports/benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump({
            "v1_results": v1_results,
            "v2_results": v2_results,
        }, f, ensure_ascii=False, indent=2)
    print("Saved: reports/benchmark_results.json")

    print(f"\nDone! Total V2 cost: ${v2_m.get('total_cost_usd', 0):.4f}")


if __name__ == "__main__":
    asyncio.run(main())
