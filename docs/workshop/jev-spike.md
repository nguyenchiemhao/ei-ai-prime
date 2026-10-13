# Spike: Jev cho Script Matcher và bộ đo Classifier

- **Cập nhật:** 2026-10-12
- **Quyết định liên quan:** D21, D22, D26, D27, D29, D30 trong [phan-bien-va-quyet-dinh.md](phan-bien-va-quyet-dinh.md)
- **Thời lượng:** 1–2 tuần, chạy song song với việc xây MVP. Ngày phát hành MVP không phụ thuộc kết quả spike.

## 1. Mục tiêu

1. **Script Matcher (bước [3]):** đo xem Jev chọn kịch bản tốt hơn reranker local bao nhiêu, và đặt ngưỡng 3 dải tin cậy cho từng nhà cung cấp.
2. **Classifier (bước [2]):** đo chất lượng của Classifier local (luật + embedding) trên 7 loại câu hỏi.
3. **Sản phẩm phụ có giá trị lâu dài:** một bộ câu test song ngữ có nhãn, dùng lại cho mọi lần đổi model (D18) và mọi lần hiệu chỉnh ngưỡng.

Ngoài phạm vi: Orchestrator, RAG, chất lượng câu trả lời sinh bởi LLM.

## 2. Điều kiện trước khi bắt đầu

| # | Việc | Người làm | Ghi chú |
|---|---|---|---|
| 1 | Đăng ký early access Jev | | Key cấp theo đợt từ danh sách chờ — đăng ký ngay |
| 2 | Đọc điều khoản dùng thử, chính sách lưu trữ, DPA của TypeSafe | | Ghi lại: gói đang dùng có lưu request không, lưu bao lâu, có dùng để train không |
| 3 | Xác nhận **chỉ dùng dữ liệu giả** | | Không có dữ liệu thật của khách hay dữ liệu cá nhân thật nào trong spike |
| 4 | Chuẩn bị model embedding và reranker local | | Ví dụ bge-m3 + bge-reranker-v2-m3 (hoặc Qwen3-Embedding/Reranker 0.6B) — cùng bộ sẽ dùng cho KB |
| 5 | Chọn điểm đo độ trễ đặt tại Việt Nam | | Đo từ máy hoặc server ở Việt Nam, không đo từ máy ở nước ngoài |

## 3. Bộ dữ liệu test

Dùng **doanh nghiệp giả định Mekong Devworks** — công ty phần mềm làm outsource (xem [design-decisions.md](../design/design-decisions.md) mục 3) — để kịch bản và câu hỏi có ngữ cảnh thống nhất với thiết kế giao diện.

### 3.1 Kịch bản

- **40 kịch bản**, mỗi kịch bản có câu trả lời song ngữ (EN/VI).
- Mỗi kịch bản có **3–5 cách hỏi mẫu cho mỗi ngôn ngữ** (đúng như cách biên tập viên sẽ nhập trong sản phẩm).
- Cố ý tạo **ít nhất 8 cặp kịch bản gần nghĩa khác ý**, ví dụ:
  - "How to request leave" / "How to cancel a leave request"
  - "OT policy on weekdays" / "OT policy on public holidays"
  - "Onboarding checklist" / "Offboarding checklist"
  - "Allowance for working at client site" / "Remote work allowance"

### 3.2 Câu test

Khoảng **400 câu**, khác với các câu hỏi mẫu đã nhập vào kịch bản. Mỗi câu có hai nhãn: `loai` (7 loại của Classifier) và `kich_ban_dung` (ID kịch bản đúng, hoặc `NONE`).

| Nhóm | Số câu | Mô tả | Nhãn `kich_ban_dung` |
|---|---|---|---|
| A. Diễn đạt khác | 120 | Cùng ý với kịch bản nhưng diễn đạt khác, EN và VI | ID kịch bản |
| B. Gõ không dấu / viết tắt | 60 | "cach xin nghi phep", "OT ngay le tinh ntn" | ID kịch bản |
| C. Gần nghĩa khác ý | 60 | Câu dễ bị khớp nhầm sang kịch bản cặp đôi | ID kịch bản đúng |
| D. Liên quan nhưng không có kịch bản | 60 | Cùng chủ đề doanh nghiệp, nhưng không kịch bản nào trả lời được | `NONE` |
| E. Ngoài phạm vi | 30 | "Viết code Python", "Giải bài toán này" | `NONE` |
| F. Chào hỏi / chuyển người | 30 | "Xin chào", "Cho tôi gặp nhân viên" | `NONE` |
| G. Câu tiếp nối | 40 | Có kèm 1–2 lượt trước; "còn cái kia thì sao?" | `NONE` (phải bỏ qua Script Matcher) |
| H. Chứa dữ liệu cá nhân | 30 | Câu nhóm A/C có thêm SĐT, email, mã nhân viên, tên | ID kịch bản |

- Tỷ lệ ngôn ngữ: khoảng 50% EN, 50% VI. Nhóm B chỉ tiếng Việt.
- Nhãn `loai` gắn cho mọi câu (nhóm A–D, H thường là `thong_tin`; một số là `tac_vu` hoặc `du_lieu`).
- **Hai người gắn nhãn độc lập** cho 100 câu ngẫu nhiên để kiểm tra nhãn có nhất quán không. Câu nào hai người bất đồng thì sửa lại định nghĩa nhãn, không chỉ sửa câu.

### 3.3 Định dạng lưu

Mỗi câu test một dòng (JSONL), các trường: `id`, `nhom`, `ngon_ngu`, `lich_su` (0–2 lượt trước), `cau_hoi`, `loai`, `kich_ban_dung`.

## 4. Che dữ liệu cá nhân (bước [1] Gate)

Áp dụng cho mọi câu trước khi đi tiếp. Nhóm H dùng để kiểm tra bước này.

| Loại | Nhãn thay thế | Ghi chú |
|---|---|---|
| Số điện thoại VN | `[SĐT]` | Đầu 0 hoặc +84, 10–11 số, có thể có dấu cách hoặc dấu chấm |
| Email | `[EMAIL]` | |
| CCCD / CMND | `[CCCD]` | 9 hoặc 12 số |
| Số tài khoản / số thẻ | `[STK]` | Dãy 8–19 số đứng riêng (cẩn thận nhầm với mã nhân viên) |
| Mã nhân viên, mã dự án | `[MÃ]` | Theo mẫu của doanh nghiệp, cấu hình được |
| Tên người dùng | `[TÊN]` | Lấy từ claim `name` trong token (D11), thay khi xuất hiện trong câu |
| Địa chỉ | — | **Không che trong spike** (regex không đáng tin); ghi nhận như một rủi ro còn lại |

Đo hai chỉ số: tỷ lệ che sót (dữ liệu cá nhân còn lọt) và tỷ lệ che nhầm (che mất thông tin không phải dữ liệu cá nhân). Kiểm tra thêm: câu đã che có còn khớp đúng kịch bản không.

## 5. Các phương án so sánh

### Script Matcher (bước [3])

| Mã | Phương án | Mô tả |
|---|---|---|
| S1 | Embedding | Chỉ dùng độ tương đồng embedding với các câu hỏi mẫu |
| S2 | Embedding + reranker local | Embedding lọc 10–20 ứng viên, reranker chấm lại (**đường mặc định của MVP**) |
| S3 | Embedding + Jev | Embedding lọc 10–20 ứng viên, Jev chọn trong ứng viên + lựa chọn "Không khớp kịch bản nào" (**theo D29**: chỉ gửi tin nhắn hiện tại đã che) |
| S4 | Embedding + LLM local giới hạn đầu ra | Model nhỏ (ví dụ Qwen3-4B) bị ép trả về một ID trong danh sách. Chạy nếu còn thời gian; đo trên GPU thuê theo giờ |

Ngưỡng lọc ứng viên của embedding dùng chung cho S2–S4: câu nào không có ứng viên vượt ngưỡng thì **không gọi bước chấm** (với S3 nghĩa là không gửi cho Jev).

### Classifier (bước [2])

| Mã | Phương án |
|---|---|
| C1 | Luật (từ khóa rõ ràng) + embedding so với câu mẫu của từng loại — **đường mặc định của MVP** |
| C2 | LLM local giới hạn đầu ra (tham khảo, nếu còn thời gian) |

Jev **không** được đo cho Classifier (D26: Jev chỉ ở bước [3]).

## 6. Chỉ số đo

### Script Matcher

| Chỉ số | Định nghĩa | Vì sao quan trọng |
|---|---|---|
| **Khớp nhầm ở dải cao** | Trong các câu được xếp dải cao, tỷ lệ chọn sai kịch bản hoặc chọn kịch bản cho câu `NONE` | **Chỉ số quan trọng nhất** — dải cao trả nguyên văn, sai là sai tự tin |
| Độ phủ dải cao | Tỷ lệ câu có kịch bản đúng được xếp dải cao | Ngưỡng quá chặt thì kịch bản vô dụng |
| Độ chính xác top-1 | Trên toàn bộ câu có `kich_ban_dung` khác `NONE` | So sánh tổng quát |
| Nhận diện `NONE` | Tỷ lệ câu nhóm D, E được xếp dải thấp | Tránh trả kịch bản cho câu không liên quan |
| Kết quả theo nhóm | Các chỉ số trên tách riêng cho nhóm B (không dấu), C (gần nghĩa), H (đã che) | Nơi các phương án thường khác nhau nhiều nhất |
| Độ tin cậy có đúng nghĩa | Chia câu theo khoảng điểm (0,9–1,0; 0,8–0,9…), so điểm trung bình với tỷ lệ đúng thực tế | Nếu báo 0,9 mà chỉ đúng 70% thì ngưỡng không có ý nghĩa |
| Độ trễ p50 / p95 | Đo từ Việt Nam, tính cả bước lọc embedding | So với ngưỡng rơi về local 800 ms (D21) |
| Tỷ lệ quá thời gian / lỗi | Với S3: số lần Jev lỗi hoặc quá 800 ms | Ước lượng tần suất rơi về local |
| Tỷ lệ gửi ra ngoài | Với S3: phần trăm câu thực sự được gửi cho Jev | Kiểm chứng D29 |
| Chi phí | Token đầu vào của Jev cho toàn bộ bộ test, quy ra 10.000 câu | |

### Classifier

- Ma trận nhầm lẫn 7 × 7.
- Độ chính xác và độ phủ cho từng loại.
- Riêng `ngoai_pham_vi`: **tỷ lệ chặn nhầm** (câu hợp lệ bị xếp ngoài phạm vi) — phải gần 0.
- Riêng `tiep_noi`: tỷ lệ nhận diện đúng trên nhóm G.

## 7. Cách đặt ngưỡng

Với mỗi phương án S2, S3:

1. Chia bộ test làm hai: **70% để chọn ngưỡng, 30% để kiểm tra** (chia theo kịch bản, không chia ngẫu nhiên từng câu, để tránh câu gần giống nhau nằm ở cả hai phần).
2. **Ngưỡng dải cao:** điểm thấp nhất mà tỷ lệ khớp nhầm ở dải cao vẫn **dưới 2%**.
3. **Ngưỡng dải trung bình:** điểm thấp nhất mà kịch bản đúng vẫn nằm trong top-1 ở ít nhất 70% trường hợp (dải này chỉ đưa kịch bản làm ngữ cảnh cho LLM nên được phép lỏng hơn).
4. Dưới ngưỡng dải trung bình là dải thấp.
5. Báo cáo kết quả trên phần 30% kiểm tra, không báo trên phần đã dùng để chọn ngưỡng.

Ngưỡng của S2 và S3 **khác nhau** và được lưu riêng (D21, điều kiện 6). Đổi model embedding, reranker hoặc phiên bản Jev thì chạy lại bước này (D18).

## 8. Tiêu chí ra quyết định

Jev được giữ là nhà cung cấp tùy chọn ở bước [3] khi **đủ cả 4 điều kiện**:

| # | Tiêu chí | Ngưỡng đề xuất |
|---|---|---|
| 1 | Chất lượng | Ở cùng tỷ lệ khớp nhầm dải cao (dưới 2%), độ phủ dải cao của S3 **cao hơn S2 ít nhất 10 điểm phần trăm**; hoặc ở cùng độ phủ, tỷ lệ khớp nhầm giảm ít nhất một nửa |
| 2 | Tiếng Việt | Nhóm B (không dấu) và các câu tiếng Việt không kém nhóm tiếng Anh quá 5 điểm phần trăm |
| 3 | Độ trễ và ổn định | p95 dưới 800 ms từ Việt Nam; tỷ lệ lỗi/quá thời gian dưới 2% |
| 4 | Pháp lý | Có DPA bằng văn bản; đã rõ chính sách lưu trữ của gói đang dùng |

Nếu không đạt tiêu chí 1–3: giữ Jev ở trạng thái thử nghiệm nội bộ, chưa mở cho khách. Nếu chỉ thiếu tiêu chí 4: không bật cho khách thật cho đến khi có DPA.

Classifier C1 đạt yêu cầu MVP khi: tỷ lệ chặn nhầm `ngoai_pham_vi` dưới 1%, và nhận diện `tiep_noi` trên 80%. Không đạt thì nới ngưỡng để nhiều câu hơn rơi về `thong_tin` (đường an toàn).

## 9. Kế hoạch thời gian

| Ngày | Việc |
|---|---|
| 1 | Đăng ký early access; đọc điều khoản; chốt doanh nghiệp giả định |
| 2–4 | Viết 40 kịch bản và 400 câu test; gắn nhãn chéo 100 câu |
| 4–5 | Chạy S1, S2, C1 (không cần key Jev) |
| Khi có key | Chạy S3; đo độ trễ từ Việt Nam |
| Nếu còn thời gian | Chạy S4, C2 trên GPU thuê theo giờ |
| Cuối spike | Đặt ngưỡng; điền bảng kết quả; ra quyết định theo mục 8 |

Nếu đến cuối tuần thứ hai vẫn chưa có key Jev: kết thúc spike với S1, S2, C1; S3 chạy bổ sung khi có key.

## 10. Mẫu bảng kết quả

### Script Matcher (trên 30% dữ liệu kiểm tra)

| Chỉ số | S1 | S2 | S3 (Jev) | S4 |
|---|---|---|---|---|
| Ngưỡng dải cao | | | | |
| Khớp nhầm ở dải cao | | | | |
| Độ phủ dải cao | | | | |
| Độ chính xác top-1 | | | | |
| Nhận diện `NONE` | | | | |
| Nhóm B (không dấu) — top-1 | | | | |
| Nhóm C (gần nghĩa) — top-1 | | | | |
| Nhóm H (đã che) — top-1 | | | | |
| Độ trễ p50 / p95 | | | | |
| Tỷ lệ lỗi / quá thời gian | — | — | | |
| Tỷ lệ câu gửi ra ngoài | — | — | | — |
| Chi phí / 10.000 câu | 0 | 0 | | |

### Classifier

| Chỉ số | C1 | C2 |
|---|---|---|
| Độ chính xác tổng | | |
| Chặn nhầm `ngoai_pham_vi` | | |
| Nhận diện `tiep_noi` | | |
| Loại bị nhầm nhiều nhất | | |

### Che dữ liệu cá nhân

| Chỉ số | Kết quả |
|---|---|
| Tỷ lệ che sót | |
| Tỷ lệ che nhầm | |
| Ảnh hưởng tới top-1 (nhóm H so với nhóm A tương ứng) | |

## 11. Rủi ro của spike

| Rủi ro | Xử lý |
|---|---|
| Chưa được cấp key Jev trong thời gian spike | Spike vẫn hoàn thành phần local; S3 chạy bổ sung sau |
| Bộ test do chính team viết nên dễ "dễ" hơn thực tế | Nhờ người ngoài team viết nhóm A và B; sau MVP thay dần bằng câu hỏi thật (đã ẩn danh) |
| Số liệu trên 400 câu dao động | Báo cáo kèm khoảng tin cậy; không kết luận từ chênh lệch dưới 3 điểm phần trăm |
| Điều khoản early access thay đổi | Ghi ngày đọc điều khoản; đọc lại trước khi bật cho khách |
