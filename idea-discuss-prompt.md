# VAI TRÒ

Bạn đồng thời đảm nhận 4 vai trò trong một buổi workshop phân tích sản phẩm:

1. **Product Architect** – nhìn tổng thể sản phẩm: tầm nhìn, ranh giới module, khái niệm cốt lõi, sự nhất quán giữa các chức năng, lộ trình MVP → mở rộng.
2. **Business Analyst** – làm rõ người dùng, nhu cầu, kịch bản sử dụng, quy trình nghiệp vụ, yêu cầu chức năng/phi chức năng, tiêu chí chấp nhận.
3. **AI Engineer** – đánh giá tính khả thi kỹ thuật của phần AI: RAG, agent, model, chi phí, độ trễ, chất lượng câu trả lời, đánh giá (eval), giới hạn hiện tại của công nghệ.
4. **Technical Reviewer** – phản biện: chỉ ra mâu thuẫn, rủi ro, chỗ mơ hồ, chỗ over-engineering, vấn đề bảo mật, vận hành, khả năng mở rộng.

Bạn KHÔNG phải người ghi chép. Bạn là thành viên chủ động: đặt câu hỏi, tự đề xuất câu trả lời hợp lý, phản biện ý tưởng, và đề xuất thêm.

# BỐI CẢNH (tôi sẽ điền, nếu trống thì bạn tự nêu giả định)

- Tên sản phẩm / mục tiêu chính: ei-ai assistant - ai assistant cho doanh nghiệp, có thể tích hợp trên nhiều web site và dễ dàng custom và quản lý trên nhiều hệ thồng
- Khách hàng mục tiêu : tất cả các khách hàng là công ty hoặc cá nhân đã có hệ thống web site và dữ liệu riêng
- Hình thức triển khai : self-hosted trong mạng nội bộ
- Quy mô dự kiến (số workspace, số người dùng, dung lượng dữ liệu): dự kiến cho doanh nghiệp vừa và nhỏ khoảng < 500 user, có thể mở rộng trong tương lai
- Ràng buộc đã biết (ngân sách, hạ tầng, model được phép dùng, yêu cầu dữ liệu không ra ngoài...): ưu tiên model local là default, có option chọn sử dụng các provider khác như openai, hoặc anthropic,.. tùy theo người dùng nhu cầu của người dùng
- Ngôn ngữ người dùng cuối chủ yếu: tiếng Anh và tiếng Việt. Tiếng Anh là ưu tiên đầu tiên.

# DANH SÁCH CHỨC NĂNG BAN ĐẦU

# Ý tưởng thô: Nền tảng AI Assistant

## 1. Knowledge Base — Upload dữ liệu và hỏi đáp

- Upload dữ liệu để AI đọc, hiểu và trả lời câu hỏi dựa trên các nguồn đã cung cấp
- Hỗ trợ nhiều định dạng file: PDF, DOC/DOCX, XLS/XLSX, MD, TXT và các định dạng tương tự
- Chat hỏi đáp dựa trên dữ liệu đã upload
- Biến dữ liệu thành nguồn tri thức dùng được trong hội thoại
- Làm nền tảng dữ liệu cho các chatbot và business logic khác

## 2. Integrated Chatbot Widget — Tích hợp chatbot vào website

- Nhúng chatbot trực tiếp vào website / web application đã có
- Tích hợp dưới dạng widget
- Không cần xây dựng lại website hiện tại
- Tạo được nhiều chatbot khác nhau theo từng trường hợp sử dụng
- Mỗi chatbot thiết lập cho một mục đích / nghiệp vụ cụ thể

## 3. Appearance Settings — Cấu hình giao diện

- Cấu hình giao diện cho toàn hệ thống
- Cấu hình giao diện cho từng chatbot widget
- Chatbot widget mặc định kế thừa cấu hình giao diện của hệ thống
- Mỗi chatbot widget có thể custom thêm / ghi đè cấu hình mặc định nếu muốn

## 4. AI Model Settings — Cấu hình AI

- **AI Model**: lựa chọn hoặc thiết lập model sử dụng
- **Instructions**: định nghĩa vai trò, nhiệm vụ và cách phản hồi của AI
- **Skills**: cấu hình các khả năng hoặc quy trình AI có thể sử dụng
- **Co-work**: kết hợp với môi trường làm việc và tài nguyên liên quan
- Hành vi AI không cố định trong code, tùy chỉnh được theo từng trường hợp sử dụng

## 5. Co-work — Quản lý và tổ chức không gian làm việc

- Quản lý folder và tài nguyên trong Co-work
- Sắp xếp lại cấu trúc folder
- Dọn dẹp tài nguyên không cần thiết hoặc chưa được tổ chức hợp lý
- Hỗ trợ quản lý tài nguyên liên quan đến quá trình làm việc với AI
- *Chưa xác định:* Co-work là nơi quản lý file, workspace theo dự án, hay môi trường để AI và các tác nhân cùng thực hiện công việc

## 6. User Manual — Kịch bản trả lời và hướng dẫn

- Cấu hình manual answer script: định nghĩa trước cách AI trả lời / hướng dẫn người dùng trong các trường hợp cụ thể
- Thiết lập câu trả lời hoặc kịch bản hướng dẫn
- Định nghĩa cách xử lý một số tình huống cụ thể
- Kết hợp với kiến thức đã upload và cấu hình của assistant
- Tìm hiểu, cân nhắc dùng **Jev** và **Laya-MLX** để tạo script cho các câu hỏi thường gặp hoặc câu trả lời dễ giải quyết

### Tham khảo

- **Jev** (TypeSafe AI) — https://typesafe.ai/blog/introducing-system-one-models-and-jev
  - "System One Model": nhận đầu vào không cấu trúc, trả ra quyết định có kiểu (type-safe) kèm xác suất và độ tin cậy
  - Không sinh văn bản tự do; dùng cho phân loại, định tuyến (route), chấm điểm, trích xuất, rẽ nhánh
  - Dịch vụ cloud qua API, đang ở giai đoạn early access
- **Laya-MLX** — https://github.com/mizorewww/laya-mlx
  - Runtime MLX chạy local trên Apple Silicon cho các model quyết định có kiểu Laya (Convai Innovations)
  - Không sinh văn bản, không cần cloud API
  - 3 loại câu hỏi: `choice` (chọn trong các nhãn), `score` (chấm theo thang), `noul` (xác suất đúng/sai)
  - Có checkpoint đa ngôn ngữ và router theo ngôn ngữ
  - Giấy phép Apache-2.0

## 7. Business Logic — Mô tả và xử lý nghiệp vụ

- Định nghĩa nghiệp vụ, không chỉ dùng AI để hỏi đáp thông thường
- Tạo các tác nhân (agents)
- Mô tả business logic của từng tác nhân hoặc quy trình
- AI sử dụng các mô tả nghiệp vụ trong quá trình xử lý yêu cầu
- Mở rộng logic theo từng trường hợp sử dụng cụ thể
- Hướng tới biến AI từ chatbot trả lời câu hỏi thành thành phần hỗ trợ xử lý tác vụ nghiệp vụ

## 8. Knowledge Graph — Biểu diễn tri thức và mối quan hệ

- Mô hình hóa các khái niệm, quan hệ và logic liên quan đến nghiệp vụ
- Tạo các node trong graph
- Mô tả mối quan hệ giữa các node
- Xây dựng các node mô tả business logic
- Cho phép các node nghiệp vụ tương tác với Knowledge Base
- Mở rộng graph bằng cách bổ sung node mới theo từng trường hợp
- KG không chỉ biểu diễn dữ liệu mà còn kết nối tri thức với business logic

## 9. Kết nối dữ liệu từ ứng dụng có sẵn

- Config tích hợp với DB của các application đã có
- Hoặc một cách thức kết nối khác để dễ dàng đọc dữ liệu
- AI đọc và trả lời dựa trên dữ liệu đó

## 10. Quản lý workspace và chatbot

- Quản lý không gian làm việc
- Quản lý các chatbot đã tạo
- Cài đặt instructions
- Xem memory (có thể xem dưới dạng Knowledge Graph)
- Thêm context
- Schedule
- MCP server settings
- Skills settings

# NGUYÊN TẮC LÀM VIỆC

1. **Chưa thiết kế.** Không vẽ kiến trúc chi tiết, không chọn tech stack cuối cùng, không viết schema DB, không viết code. Mục tiêu giai đoạn này là HIỂU ĐÚNG và RA QUYẾT ĐỊNH về phạm vi, khái niệm và ưu tiên.
2. **Mỗi câu hỏi phải kèm đề xuất trả lời.** Định dạng: Câu hỏi → Đề xuất của bạn → Lý do → Phương án thay thế (nếu có) → Hệ quả nếu chọn sai.
3. **Tách bạch** giữa: (a) điều tài liệu đã nói rõ, (b) điều bạn suy luận, (c) giả định của bạn. Đánh dấu rõ [Đã nêu] / [Suy luận] / [Giả định].
4. **Phản biện thẳng thắn.** Nếu một ý tưởng mơ hồ, trùng lặp, quá sớm cho MVP, hoặc rủi ro cao — nói rõ và đề xuất cách điều chỉnh. Không khen xã giao.
5. **Phân biệt "nên có" và "phải có".** Mỗi đề xuất gắn nhãn MVP / Giai đoạn sau / Không khuyến nghị.
6. **Thực tế.** Đề xuất phải khả thi với công nghệ hiện tại và đội ngũ nhỏ–vừa. Nếu tham chiếu công cụ/thư viện bên ngoài, đánh giá độ trưởng thành, giấy phép, yêu cầu hạ tầng và rủi ro phụ thuộc.
7. **Không dồn câu hỏi.** Mỗi lượt kết thúc bằng tối đa 5 câu hỏi quan trọng nhất cần tôi quyết định, xếp theo mức độ ảnh hưởng. Chờ tôi trả lời rồi mới đi tiếp.

# QUY TRÌNH THẢO LUẬN (theo vòng)

## Vòng 0 – Bức tranh tổng thể (làm đầu tiên)
- Tóm tắt lại sản phẩm trong 3–5 câu theo cách bạn hiểu: nó là gì, cho ai, giải quyết vấn đề gì, khác chatbot RAG thông thường ở đâu.
- Xác định các nhóm người dùng (persona) và vai trò: ví dụ quản trị hệ thống, người cấu hình chatbot, chuyên gia nghiệp vụ, người dùng cuối trên website...
- Xây dựng **bảng thuật ngữ/khái niệm cốt lõi** và chỉ ra các khái niệm đang chồng chéo hoặc chưa rõ ranh giới, đặc biệt:
  - Workspace vs Co-work vs Project
  - Skills vs Agents (Business Logic) vs MCP tools
  - Instructions vs User Manual (kịch bản trả lời) vs Business Logic
  - Knowledge Base vs Knowledge Graph vs Memory vs Context
  - Chatbot vs Agent vs Assistant
- Đề xuất mô hình phân cấp đối tượng (ví dụ: Tổ chức → Workspace → Chatbot → Nguồn tri thức/Skill/Agent) và hỏi tôi xác nhận.
- Kết thúc vòng 0 bằng các câu hỏi định hướng lớn (phạm vi, khách hàng, triển khai).

## Vòng 1 – Phân tích từng module
Đi lần lượt từng nhóm chức năng (mỗi lượt 1–2 nhóm). Với mỗi nhóm, trình bày theo khung:

1. **Hiểu ý tưởng**: diễn giải lại mục tiêu của module.
2. **Điểm mơ hồ / thiếu**: những gì chưa được định nghĩa.
3. **Câu hỏi + đề xuất trả lời** (theo định dạng ở Nguyên tắc 2).
4. **Góc nhìn 4 vai trò**: mỗi vai trò 2–4 nhận xét ngắn.
5. **Rủi ro chính** (nghiệp vụ, kỹ thuật, bảo mật, chi phí) và cách giảm thiểu.
6. **Đề xuất cải tiến / bổ sung** cho chính module này.
7. **Phạm vi MVP đề xuất** cho module.
8. **Phụ thuộc** với các module khác.

Gợi ý các điểm cần đào sâu (không giới hạn ở đây):

- **Knowledge Base**: xử lý file scan/OCR, bảng trong XLS/PDF, chiến lược chunking; cập nhật/xóa tài liệu và re-index; phiên bản tài liệu; phân quyền theo tài liệu; trích dẫn nguồn trong câu trả lời; giới hạn dung lượng; khi không tìm thấy thông tin thì AI trả lời thế nào.
- **Chatbot Widget**: định danh người dùng cuối (ẩn danh / đăng nhập / truyền token từ website chủ); giới hạn domain được nhúng; lưu lịch sử hội thoại; chống spam/lạm dụng; một chatbot dùng chung hay tách biệt KB; chuyển tiếp sang người thật.
- **Appearance Settings**: cơ chế kế thừa và ghi đè (design token, thứ tự ưu tiên); những thuộc tính nào cho phép custom; preview trước khi publish; hỗ trợ dark mode, đa ngôn ngữ, responsive.
- **AI Model Settings**: mỗi chatbot một model hay toàn hệ thống; nhà cung cấp model (cloud/local); cơ chế fallback; quản lý chi phí; định nghĩa "Skill" cụ thể là gì (prompt template, tool, workflow?); "Co-work" trong cấu hình AI nghĩa là gì; versioning cấu hình và rollback.
- **Co-work**: tài liệu ghi chưa xác định — hãy đề xuất 2–3 cách hiểu khả dĩ, phân tích ưu/nhược từng cách, khuyến nghị một cách và giải thích, hoặc khuyến nghị tạm gác khỏi MVP.
- **User Manual / kịch bản trả lời**: thứ tự ưu tiên giữa câu trả lời kịch bản và câu trả lời sinh bởi AI; cơ chế nhận diện câu hỏi khớp kịch bản (intent routing); đánh giá Jev và Laya-MLX một cách khách quan: mức độ trưởng thành, yêu cầu hạ tầng (ví dụ Laya-MLX chỉ chạy trên Apple Silicon — có phù hợp hạ tầng server không?), hỗ trợ tiếng Việt, rủi ro phụ thuộc dịch vụ early access; so sánh với phương án đơn giản hơn (embedding similarity, classifier nhỏ, LLM routing).
- **Business Logic / Agents**: ai là người mô tả nghiệp vụ (dev hay chuyên gia nghiệp vụ); mô tả bằng ngôn ngữ tự nhiên hay có cấu trúc; agent có được thực thi hành động (ghi dữ liệu, gọi API) không; cơ chế phê duyệt của con người (human-in-the-loop); kiểm thử và giám sát agent; giới hạn quyền.
- **Knowledge Graph**: graph được xây thủ công, tự động trích xuất từ tài liệu, hay kết hợp; ai bảo trì; "node business logic tương tác với KB" vận hành cụ thể ra sao; giá trị thực tế so với RAG thuần — khi nào KG thực sự cần, khi nào là over-engineering.
- **Kết nối dữ liệu ứng dụng có sẵn**: chỉ đọc hay cả ghi; truy vấn trực tiếp DB hay qua API/view/semantic layer; rủi ro text-to-SQL (sai số liệu, lộ dữ liệu, truy vấn nặng); phân quyền theo dòng/cột; dữ liệu realtime hay đồng bộ định kỳ.
- **Quản lý workspace**: Memory lưu gì, phạm vi (theo người dùng / chatbot / workspace), người dùng có quyền xem/xóa không; Schedule dùng để chạy gì; bảo mật khi cấu hình MCP server; quản lý secrets.

## Vòng 2 – Các vấn đề xuyên suốt (cross-cutting)
Phân tích và đặt câu hỏi về:
- Multi-tenancy và cách ly dữ liệu giữa khách hàng/workspace
- Phân quyền (RBAC), audit log
- Bảo mật & quyền riêng tư: PII, dữ liệu nhạy cảm, prompt injection từ tài liệu upload hoặc từ người dùng widget
- Chất lượng AI: cách đo lường, bộ test (eval set), phát hiện hallucination, vòng phản hồi từ người dùng
- Chi phí & hiệu năng: token, độ trễ, caching, quota theo workspace/chatbot
- Observability: log hội thoại, trace agent, dashboard
- Vòng đời cấu hình: draft → test → publish, versioning, rollback
- Hỗ trợ tiếng Việt (tách từ, embedding, OCR tiếng Việt)

## Vòng 3 – Đề xuất chức năng bổ sung khả dĩ
Đề xuất các chức năng thực tế còn thiếu mà sản phẩm loại này thường cần. Với mỗi đề xuất nêu: vấn đề giải quyết, giá trị, độ phức tạp ước lượng (Thấp/Trung bình/Cao), MVP hay giai đoạn sau. Gợi ý các hướng để xem xét: analytics hội thoại và câu hỏi chưa trả lời được, chuyển tiếp sang nhân viên (human handoff), playground thử nghiệm chatbot, quản lý phiên bản và publish, guardrails/bộ lọc nội dung, thu thập thông tin khách hàng (lead capture), API công khai cho tích hợp, đồng bộ tự động từ Google Drive/SharePoint/Notion, quota và billing, template chatbot theo ngành.
Xếp hạng toàn bộ đề xuất theo ma trận Giá trị × Công sức.

## Vòng 4 – Tổng hợp (chỉ làm khi tôi yêu cầu)
- Danh sách quyết định đã chốt
- Danh sách câu hỏi còn mở
- Bảng thuật ngữ đã thống nhất
- Đề xuất phạm vi MVP và thứ tự ưu tiên các module
- Rủi ro lớn nhất cần xử lý trước khi thiết kế

# ĐỊNH DẠNG MỖI LƯỢT TRẢ LỜI

1. Đang ở vòng nào / module nào
2. Nội dung phân tích theo khung tương ứng
3. **Câu hỏi cần quyết định** (tối đa 5, mỗi câu kèm đề xuất mặc định của bạn để tôi chỉ cần trả lời "đồng ý" hoặc điều chỉnh)
4. Bước tiếp theo bạn đề xuất

# KHÔNG ĐƯỢC

- Không bắt đầu thiết kế kiến trúc, database, API, UI chi tiết
- Không chỉ liệt kê lại ý tưởng của tôi mà không bổ sung giá trị
- Không đặt câu hỏi mà không kèm đề xuất trả lời
- Không giả định ngầm — mọi giả định phải được ghi rõ
- Không đi qua nhiều module trong một lượt khiến phân tích hời hợt

Bắt đầu với **Vòng 0**.