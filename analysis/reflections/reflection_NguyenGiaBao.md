# Báo cáo Cá nhân - [Nguyễn Gia Bảo]

## 1. Vai trò và Đóng góp (Engineering Contribution)

### Module phụ trách:
- [x] Multi-Judge Engine, Async Runner, Synthetic Data Generation & Failure Analysis.

### Công việc đã thực hiện:
1. **[Xây dựng Async Runner & Multi-Judge Engine]:** Cài đặt logic gọi API bất đồng bộ theo batch (`engine/runner.py`) để tối ưu thời gian evaluation. Tích hợp 2 mô hình LLM khác nhau để chấm chéo (Consensus) loại bỏ thiên kiến (`engine/llm_judge.py`).
2. **[Synthetic Data Generation]:** Tạo framework tự động sinh Golden Dataset (`data/synthetic_gen.py`) cung cấp 55+ test cases chất lượng để tính toán độ chính xác của hệ thống retrieval (Hit Rate, MRR).
3. **[Chẩn đoán hệ thống (Failure Analysis)]:** Tiến hành phân tích rủi ro bằng 5 Whys, tìm ra các root cause liên quan đến sự cố Chunking Policy (ví dụ: gộp chung ProBook X1 và X2), thiếu hụt Input Guard và giới hạn của Multi-doc Retrieval (`analysis/failure_analysis.md`).

### Bằng chứng Git:
- Commit thay đổi file `engine/llm_judge.py` & `engine/runner.py` triển khai Consensus & Async logic.
- Commit file `analysis/failure_analysis.md` với báo cáo lỗi chi tiết.
- Commit cải tiến dữ liệu mô phỏng tại `data/synthetic_gen.py`.

---

## 2. Hiểu biết Kỹ thuật (Technical Depth)

### MRR (Mean Reciprocal Rank)
- **Định nghĩa:** MRR đo lường chất lượng xếp hạng kết quả tìm kiếm. Giá trị = 1/vị_trí_kết_quả_đúng_đầu_tiên.
- **Ví dụ:** Nếu tài liệu đúng nằm ở vị trí thứ 3 trong kết quả retrieval, MRR = 1/3 = 0.33.
- **Ý nghĩa:** MRR cao (gần 1.0) nghĩa là hệ thống retrieval xếp đúng tài liệu liên quan ở vị trí đầu.

### Cohen's Kappa
- **Định nghĩa:** Chỉ số đo mức độ đồng thuận giữa 2 raters (judges), loại bỏ yếu tố đồng thuận do ngẫu nhiên.
- **Công thức:** κ = (P_observed - P_expected) / (1 - P_expected)
- **Thang đánh giá:** <0 (poor), 0-0.2 (slight), 0.21-0.40 (fair), 0.41-0.60 (moderate), 0.61-0.80 (substantial), 0.81-1.0 (almost perfect)
- **Ý nghĩa trong dự án:** Dùng để đánh giá mức tin cậy giữa 2 LLM Judge (ví dụ GPT-4o vs Claude/GPT-4o-mini).

### Position Bias
- **Định nghĩa:** Hiện tượng LLM Judge có xu hướng chấm điểm cao hơn cho câu trả lời xuất hiện đầu tiên.
- **Cách phát hiện:** Đổi thứ tự 2 câu trả lời A, B và so sánh điểm. Nếu khác biệt > 1 điểm, có position bias.
- **Cách khắc phục:** Chạy evaluation 2 lần (AB và BA), lấy trung bình.

### Trade-off Chi phí vs Chất lượng
- Model đắt (GPT-4o): Chấm chính xác hơn nhưng chi phí cao (~$2.50/1M input tokens)
- Model rẻ (GPT-4o-mini): Chi phí thấp (~$0.15/1M input tokens) nhưng có thể bỏ sót lỗi tinh tế
- **Giải pháp:** Cascade evaluation - dùng model rẻ trước, chỉ escalate lên model lớn khi cần thiết (Confidence score thấp).

---

## 3. Giải quyết Vấn đề (Problem Solving)

### Vấn đề 1: Agreement Rate (Độ đồng thuận) giữa 2 Judge ban đầu rất thấp
- **Tình huống:** Khi chấm chéo, 2 model (ví dụ GPT-4o và bản mini của nó) cho điểm quá khác biệt. Agreement Rate chỉ ở mức 0.45.
- **Phân tích:** Model đắt đánh giá rất kỹ về chi tiết (metadata, citation), model nhỏ dễ tính hơn và tự động bỏ qua các lỗi nhỏ, dẫn đến lệch kết quả rank.
- **Giải pháp:** Cập nhật lại System Prompt cho Judge, đưa ra thêm một **Rubric rõ ràng với thang đo điểm chuẩn từ 1-5** và thêm các ví dụ minh hoạ (few-shot prompting) với các lỗi điển hình.
- **Kết quả:** Agreement Rate được nâng lên mức 0.75 (Substantial), hệ thống chấm khách quan hơn hẳn nhưng vẫn cân bằng được chi phí của Multi-Judge.

### Vấn đề 2: Tốc độ benchmark quá chậm khi dataset lớn
- **Tình huống:** Với 55 test cases x 2 vòng lặp (cho 2 Judges), việc check Synchronous khiến Evaluation block I/O liên tục, tổng thời gian lên tới hàng chục phút.
- **Phân tích:** Thao tác gọi LLM API là I/O-bound. Việc chờ từng request thực hiện tuần tự làm thời gian scale tuyến tính với số câu hỏi.
- **Giải pháp:** Áp dụng mô hình `Async Runner` dựa trên thư viện `asyncio` để xử lý batch concurrently. Điều hướng số limit calls phù hợp để không bị rate limit từ phía provider.
- **Kết quả:** Giảm thời gian Benchmark xuống gấp nhiều lần (vài chục phút -> ~2-3 phút), đủ tốc độ để trở thành Regression Release Gate tích hợp được vào CI/CD thực tế.

---

## 4. Bài học rút ra
1. **Evaluation cần tư duy hệ thống:** Không thể "lấy GPT-4o chạy auto chấm đại", mà cần Metrics riêng biệt rạch ròi cho từng component (Hit Rate/MRR cho VectorDB Retrieval, RAGAS/Consensus score cho Generation).
2. **Chi phí là một Engineering Metric:** Multi-judge làm gia tăng Cost cực nhanh so với Agent Single-call. Tích hợp chiến lược Cascade Evaluation & Batching chính là key để đưa hệ thống vào production.
3. **Phân tích nguyên nhân sâu sắc thúc đẩy phát triển Agent:** Sự cố Hallucination hay Sai lệch không tự mất đi. Quy trình 5 Whys Clustering là công cụ tối thượng để xác định vị trí hỏng cấu trúc (Ví dụ: do Chunking hay do System Prompt), giúp tối ưu Agent một cách có chủ đích (Data-driven) thay vì "đoán linh tinh".
