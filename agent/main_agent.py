import asyncio
import random
import hashlib
from typing import List, Dict

# Simulated document store matching the IDs used in golden_set
DOCUMENT_STORE = {
    "doc_policy_001": "Chính sách bảo mật thông tin khách hàng - mã hóa AES-256, lưu trữ 5 năm, xóa qua hotline hoặc email",
    "doc_policy_002": "Quy trình đổi trả hàng hóa - 30 ngày, điện tử 7 ngày, giảm giá >50% không đổi trả",
    "doc_policy_003": "Chính sách bảo hành - 12 tháng, lỗi kỹ thuật nhà sản xuất, 14 ngày sửa chữa",
    "doc_hr_001": "Quy định nghỉ phép - 12 ngày/năm, thâm niên +1 ngày/5 năm, chuyển tối đa 5 ngày",
    "doc_hr_002": "Chính sách lương thưởng - ngày 5 và 20, KPI A/B/C/D, thưởng Tết 1 tháng lương",
    "doc_tech_001": "Hướng dẫn đổi mật khẩu - portal.company.vn, 8 ký tự, đổi mỗi 90 ngày",
    "doc_tech_002": "Quy trình sự cố - P1 1h, P2 4h, P3 24h, P4 1 tuần, postmortem 48h",
    "doc_product_001": "ProBook X1 - i7-13700H, 16GB, 512GB, 25,990,000 VND, bảo hành 24 tháng",
    "doc_product_002": "ProBook X2 - i5-13500H, 8GB, 256GB, 15,990,000 VND, bảo hành 12 tháng",
    "doc_finance_001": "Thanh toán và hoàn tiền - Visa/MC/JCB, MoMo/ZaloPay, trả góp 0%, VAT 3 ngày",
}

ALL_DOC_IDS = list(DOCUMENT_STORE.keys())

ANSWER_TEMPLATES = {
    "good": "Dựa trên tài liệu hệ thống, {answer_content}",
    "partial": "Theo thông tin tôi có, {answer_content} Tuy nhiên, tôi không chắc chắn về một số chi tiết.",
    "off_topic": "Tôi xin phép trả lời rằng {generic_content}",
    "hallucination": "Theo quy định của công ty, {fabricated_content}",
    "refusal": "Tôi không thể thực hiện yêu cầu này vì {reason}. Vui lòng đặt câu hỏi liên quan đến sản phẩm và dịch vụ.",
}


class MainAgent:
    """
    RAG Agent simulation with realistic behavior patterns.
    Returns varied responses including correct, partial, and incorrect answers
    to create realistic evaluation scenarios.
    """

    def __init__(self, version: str = "v1", noise_level: float = 0.15):
        self.name = f"SupportAgent-{version}"
        self.version = version
        self.noise_level = noise_level
        self.total_tokens = 0
        self.query_count = 0

    def _simulate_retrieval(self, question: str, expected_ids: List[str] = None) -> List[str]:
        """
        Simulate vector DB retrieval. Returns a list of doc IDs.
        Has a configurable chance of retrieving wrong documents.
        """
        seed = int(hashlib.md5(question.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed + hash(self.version))

        if expected_ids:
            retrieved = list(expected_ids)
        else:
            retrieved = rng.sample(ALL_DOC_IDS, min(3, len(ALL_DOC_IDS)))

        if rng.random() < self.noise_level:
            wrong_docs = [d for d in ALL_DOC_IDS if d not in retrieved]
            if wrong_docs:
                idx = rng.randint(0, len(retrieved) - 1) if retrieved else 0
                if retrieved:
                    retrieved[idx] = rng.choice(wrong_docs)
                else:
                    retrieved.append(rng.choice(wrong_docs))

        other_docs = [d for d in ALL_DOC_IDS if d not in retrieved]
        padding = rng.sample(other_docs, min(2, len(other_docs)))
        retrieved.extend(padding)

        return retrieved[:5]

    def _generate_answer(self, question: str, retrieved_ids: List[str], expected_answer: str = "") -> str:
        """Generate a response based on retrieved documents and question type."""
        seed = int(hashlib.md5(question.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed + hash(self.version))

        adversarial_keywords = ["bỏ qua", "ignore", "system:", "override", "giả vờ", "mật khẩu admin",
                                "thẻ tín dụng", "xóa ngay", "mã giảm giá 99", "/etc/passwd", "số điện thoại cá nhân"]
        is_adversarial = any(kw.lower() in question.lower() for kw in adversarial_keywords)

        if is_adversarial:
            if rng.random() < 0.85:
                return ANSWER_TEMPLATES["refusal"].format(
                    reason="đây là yêu cầu vi phạm chính sách bảo mật và an toàn hệ thống"
                )
            return f"Tôi hiểu câu hỏi của bạn. {expected_answer[:100] if expected_answer else 'Tôi không thể hỗ trợ yêu cầu này.'}"

        oot_keywords = ["bitcoin", "thủ đô", "nấu phở", "tổng thống", "teambuilding"]
        is_out_of_topic = any(kw.lower() in question.lower() for kw in oot_keywords)

        if is_out_of_topic:
            if rng.random() < 0.7:
                return "Câu hỏi này nằm ngoài phạm vi hỗ trợ của tôi. Tôi chỉ trả lời các câu hỏi liên quan đến sản phẩm và dịch vụ của công ty."
            return f"Tôi không chắc chắn nhưng {expected_answer[:80] if expected_answer else 'tôi không có thông tin về vấn đề này.'}"

        roll = rng.random()
        if roll < 0.55:
            answer = expected_answer if expected_answer else "Dựa trên tài liệu, đây là thông tin bạn cần."
            return ANSWER_TEMPLATES["good"].format(answer_content=answer)
        elif roll < 0.75:
            partial = expected_answer[:len(expected_answer)//2] if expected_answer else "thông tin liên quan"
            return ANSWER_TEMPLATES["partial"].format(answer_content=partial)
        elif roll < 0.90:
            contexts = [DOCUMENT_STORE.get(did, "") for did in retrieved_ids[:2]]
            return ANSWER_TEMPLATES["off_topic"].format(
                generic_content=f"theo tài liệu: {'; '.join(contexts[:1])}"
            )
        else:
            return ANSWER_TEMPLATES["hallucination"].format(
                fabricated_content="thời gian xử lý là 48 giờ và chi phí là 500,000 VND (thông tin có thể không chính xác)."
            )

    async def query(self, question: str, expected_answer: str = "", expected_retrieval_ids: List[str] = None) -> Dict:
        """
        Simulate RAG pipeline: Retrieve -> Generate.
        Returns structured response with answer, contexts, and metadata.
        """
        await asyncio.sleep(random.uniform(0.05, 0.3))

        retrieved_ids = self._simulate_retrieval(question, expected_retrieval_ids)
        contexts = [DOCUMENT_STORE.get(did, f"Context for {did}") for did in retrieved_ids[:3]]
        answer = self._generate_answer(question, retrieved_ids, expected_answer)

        tokens_used = len(answer.split()) * 2 + len(question.split()) * 1.5
        tokens_used = int(tokens_used + random.randint(50, 150))
        self.total_tokens += tokens_used
        self.query_count += 1

        return {
            "answer": answer,
            "contexts": contexts,
            "metadata": {
                "model": "gpt-4o-mini",
                "tokens_used": tokens_used,
                "retrieved_ids": retrieved_ids,
                "sources": [f"{did}.pdf" for did in retrieved_ids[:3]],
                "agent_version": self.version,
            },
        }

    def get_stats(self) -> Dict:
        return {
            "total_queries": self.query_count,
            "total_tokens": self.total_tokens,
            "avg_tokens_per_query": self.total_tokens / max(self.query_count, 1),
            "estimated_cost_usd": self.total_tokens * 0.15 / 1_000_000,
        }


class OptimizedAgent(MainAgent):
    """
    V2 Agent with improvements: lower noise, better retrieval, refined prompts.
    Used for regression testing against the base agent.
    """

    def __init__(self):
        super().__init__(version="v2", noise_level=0.05)


if __name__ == "__main__":
    agent = MainAgent()
    async def test():
        resp = await agent.query(
            "Làm thế nào để đổi mật khẩu?",
            expected_answer="Đăng nhập portal.company.vn, vào Cài đặt > Bảo mật > Đổi mật khẩu.",
            expected_retrieval_ids=["doc_tech_001"],
        )
        print(json.dumps(resp, ensure_ascii=False, indent=2))
    import json
    asyncio.run(test())
