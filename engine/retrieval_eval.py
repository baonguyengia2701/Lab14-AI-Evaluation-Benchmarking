from typing import List, Dict, Any, Tuple


class RetrievalEvaluator:
    def __init__(self):
        self._results: List[Dict] = []

    def calculate_hit_rate(self, expected_ids: List[str], retrieved_ids: List[str], top_k: int = 3) -> float:
        """
        Check if at least one expected_id appears in the top_k retrieved results.
        Returns 1.0 (hit) or 0.0 (miss).
        """
        if not expected_ids:
            return 1.0
        top_retrieved = retrieved_ids[:top_k]
        hit = any(doc_id in top_retrieved for doc_id in expected_ids)
        return 1.0 if hit else 0.0

    def calculate_mrr(self, expected_ids: List[str], retrieved_ids: List[str]) -> float:
        """
        Mean Reciprocal Rank: 1 / position of the first relevant document (1-indexed).
        Returns 0.0 if no relevant document is found.
        """
        if not expected_ids:
            return 1.0
        for i, doc_id in enumerate(retrieved_ids):
            if doc_id in expected_ids:
                return 1.0 / (i + 1)
        return 0.0

    def calculate_precision_at_k(self, expected_ids: List[str], retrieved_ids: List[str], k: int = 3) -> float:
        """Precision@K: fraction of top-k retrieved docs that are relevant."""
        if not expected_ids or k == 0:
            return 0.0
        top_k = retrieved_ids[:k]
        relevant = sum(1 for doc_id in top_k if doc_id in expected_ids)
        return relevant / k

    def calculate_recall(self, expected_ids: List[str], retrieved_ids: List[str]) -> float:
        """Recall: fraction of expected docs that were retrieved."""
        if not expected_ids:
            return 1.0
        found = sum(1 for doc_id in expected_ids if doc_id in retrieved_ids)
        return found / len(expected_ids)

    def evaluate_single(self, expected_ids: List[str], retrieved_ids: List[str], top_k: int = 3) -> Dict[str, float]:
        """Evaluate a single retrieval result across all metrics."""
        result = {
            "hit_rate": self.calculate_hit_rate(expected_ids, retrieved_ids, top_k),
            "mrr": self.calculate_mrr(expected_ids, retrieved_ids),
            "precision_at_k": self.calculate_precision_at_k(expected_ids, retrieved_ids, top_k),
            "recall": self.calculate_recall(expected_ids, retrieved_ids),
        }
        self._results.append(result)
        return result

    async def evaluate_batch(self, dataset: List[Dict], agent_responses: List[Dict] = None) -> Dict[str, Any]:
        """
        Evaluate retrieval quality for the entire dataset.

        Each item in dataset should have 'expected_retrieval_ids'.
        Each agent_response should have metadata.retrieved_ids.
        If agent_responses is None, uses retrieved_ids already embedded in dataset items.
        """
        per_case_results = []
        hit_rates = []
        mrrs = []
        precisions = []
        recalls = []

        for i, case in enumerate(dataset):
            expected_ids = case.get("expected_retrieval_ids", [])

            if agent_responses and i < len(agent_responses):
                resp = agent_responses[i]
                retrieved_ids = resp.get("metadata", {}).get("retrieved_ids", [])
            else:
                retrieved_ids = case.get("retrieved_ids", [])

            metrics = self.evaluate_single(expected_ids, retrieved_ids)
            hit_rates.append(metrics["hit_rate"])
            mrrs.append(metrics["mrr"])
            precisions.append(metrics["precision_at_k"])
            recalls.append(metrics["recall"])

            per_case_results.append({
                "case_index": i,
                "question": case.get("question", ""),
                "expected_ids": expected_ids,
                "retrieved_ids": retrieved_ids,
                **metrics,
            })

        n = len(dataset) if dataset else 1
        avg_hit_rate = sum(hit_rates) / n
        avg_mrr = sum(mrrs) / n

        failures = [r for r in per_case_results if r["hit_rate"] == 0.0]

        return {
            "avg_hit_rate": round(avg_hit_rate, 4),
            "avg_mrr": round(avg_mrr, 4),
            "avg_precision_at_k": round(sum(precisions) / n, 4),
            "avg_recall": round(sum(recalls) / n, 4),
            "total_cases": n,
            "hits": sum(1 for h in hit_rates if h == 1.0),
            "misses": sum(1 for h in hit_rates if h == 0.0),
            "per_case": per_case_results,
            "failure_cases": failures,
        }

    @staticmethod
    def correlate_retrieval_with_quality(retrieval_results: List[Dict], judge_scores: List[float]) -> Dict:
        """
        Analyze the relationship between retrieval quality and answer quality.
        Shows that good retrieval leads to good answers and vice versa.
        """
        if not retrieval_results or not judge_scores:
            return {"correlation": "insufficient_data"}

        hit_scores = []
        miss_scores = []

        for i, ret in enumerate(retrieval_results):
            if i < len(judge_scores):
                if ret.get("hit_rate", 0) == 1.0:
                    hit_scores.append(judge_scores[i])
                else:
                    miss_scores.append(judge_scores[i])

        avg_hit = sum(hit_scores) / len(hit_scores) if hit_scores else 0
        avg_miss = sum(miss_scores) / len(miss_scores) if miss_scores else 0

        return {
            "avg_score_when_hit": round(avg_hit, 2),
            "avg_score_when_miss": round(avg_miss, 2),
            "score_delta": round(avg_hit - avg_miss, 2),
            "hit_cases": len(hit_scores),
            "miss_cases": len(miss_scores),
            "conclusion": (
                f"When retrieval is successful (hit), average judge score is {avg_hit:.2f}. "
                f"When retrieval fails (miss), average judge score is {avg_miss:.2f}. "
                f"Delta: {avg_hit - avg_miss:+.2f}. "
                + ("This confirms that retrieval quality directly impacts answer quality."
                   if avg_hit > avg_miss else
                   "No clear correlation found - answer quality issues may be in generation, not retrieval.")
            ),
        }
