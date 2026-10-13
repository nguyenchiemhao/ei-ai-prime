# ei-ai assistant — Phản biện, câu hỏi & quyết định

- **Cập nhật:** 2026-10-13
- **Giai đoạn:** Workshop phân tích sản phẩm — **đã xong Vòng 0, Vòng 1, Vòng 2**; tổng hợp ở [tong-hop.md](tong-hop.md). Vòng 3 (chức năng bổ sung) để sau khi có bản thử. Vòng 1 gồm Module 1 (Knowledge Base), Module 2 (Chatbot Widget), Module 3 (Appearance), Module 4 (AI Model Settings), Module 6 (Answer Scripts), pipeline xử lý câu hỏi, Module 7 + 9 (Skills/Tools, Data Connectors) và Module 10 (Memory, Schedule, MCP)
- **Nguồn:** các phiên thảo luận theo [idea-discuss-prompt.md](../../idea-discuss-prompt.md)

## Cách dùng tài liệu này

Mỗi mục phản biện có nhãn phạm vi sử dụng:

- **[Nội bộ]** — phân tích cạnh tranh, rủi ro, điểm yếu. Dùng để ra quyết định, không đưa ra ngoài.
- **[Đối ngoại được]** — có thể chuyển thành nội dung trả lời khách hàng hoặc truyền thông, **với điều kiện tính năng/cam kết đó đã thực sự được triển khai**. Không quảng bá một cam kết khi hệ thống chưa thực thi được nó.

---

## 1. Định vị sản phẩm (đã chốt)

> Trợ lý AI nhúng vào web app sẵn có của doanh nghiệp, biết người dùng đang đăng nhập là ai, đọc và thao tác được trên dữ liệu của chính app đó, hỗ trợ tốt tiếng Việt và tiếng Anh.
>
> Dữ liệu của bạn không được gửi cho bất kỳ nhà cung cấp AI bên thứ ba nào, trừ khi bạn chủ động bật. Có thể triển khai riêng trên hạ tầng của bạn.

Câu định vị ban đầu dùng cụm "chạy hoàn toàn nội bộ" đã được sửa, vì ở chế độ vận hành tập trung dữ liệu của khách nằm trên hạ tầng của nhà cung cấp, không nằm trong mạng nội bộ của khách (xem P7).

---

## 2. Quyết định đã chốt

| # | Quyết định | Vòng |
|---|---|---|
| D1 | **Triển khai:** hướng chính là một bản cài tập trung do bên mình vận hành cho nhiều khách hàng (mỗi khách hàng là một Organization; cần cách ly, quota, billing ngay MVP). Hướng phụ: khách tự host trên hạ tầng riêng, tùy hợp đồng. | 0 |
| D2 | **Người dùng cuối:** ưu tiên người dùng đã đăng nhập trên web app của khách; website chủ truyền token định danh vào widget. Chế độ ẩn danh được hỗ trợ nhưng giới hạn: chỉ tri thức công khai, không Tool/Connector, có giới hạn tần suất. | 0 |
| D3 | **Định vị:** như mục 1. | 0 |
| D4 | **Phần cứng:** định nghĩa cấu hình tham chiếu (Linux x86 + GPU NVIDIA 24–48 GB VRAM). Môi trường dev bắt đầu với phần cứng hiện có, đầu tư thêm khi sản phẩm ổn định. Điều kiện: gọi model qua API chuẩn tương thích OpenAI, có bộ eval từ tuần đầu, đo chất lượng trên GPU thuê theo giờ, dev chỉ dùng dữ liệu giả với model cloud. | 0 |
| D5 | **Mô hình khái niệm:** tách Assistant và Channel; Business Logic = Skill + Tool; MCP chỉ là một nguồn cung cấp Tool; "User Manual" đổi thành "Answer Scripts"; Data Connector tách khỏi Knowledge Base; Knowledge Graph ra khỏi MVP. "Co-work/Project" được hiểu như Claude Projects — chọn file/folder làm phạm vi tri thức — và đổi tên thành **Knowledge Scope**. | 0 |
| D6 | **Nền tảng:** một codebase duy nhất, luôn chạy multi-tenant; bản tự host là bản multi-tenant chạy một Organization. Nhân sự vận hành mặc định **không** xem được dữ liệu khách; quyền hỗ trợ do khách cấp, có thời hạn, ghi audit. | 1 |
| D7 | **Billing MVP:** đo mức sử dụng theo Organization (token, dung lượng, số tin nhắn), chặn cứng khi vượt quota, xuất hóa đơn thủ công. Chưa tích hợp cổng thanh toán. | 1 |
| D8 | **Phân quyền tri thức:** 3 mức theo Collection — Public / Authenticated / Restricted (theo nhóm lấy từ token của app chủ). Lọc theo quyền **trước khi** đưa vào LLM. Quyền theo từng tài liệu để giai đoạn sau. | 1 |
| D9 | **OCR:** chuyển sang giai đoạn sau. MVP tự phát hiện PDF dạng scan và báo rõ là chưa hỗ trợ. | 1 |
| D10 | **Excel:** MVP chỉ hỗ trợ tra cứu ("giá sản phẩm X"), không tính toán ("tổng doanh thu quý 3"). Nhu cầu tính toán chuyển sang Connector/Tool ở giai đoạn sau. | 1 |
| D11 | **Định danh người dùng widget:** backend của website chủ ký token ngắn hạn (JWT) bằng khóa riêng của từng Channel; token chứa user ID, tên, nhóm. Hỗ trợ hai khóa song song để xoay vòng. Thông tin ảnh hưởng quyền bắt buộc nằm trong token đã ký; session variables không ký bị coi là dữ liệu không đáng tin. OIDC/SSO để giai đoạn sau. | 1 |
| D12 | **Công nghệ nhúng:** snippet nhỏ tạo iframe; token truyền qua postMessage, không dùng cookie. Module 3 chỉ tùy biến bằng cấu hình, không có CSS tự do. | 1 |
| D13 | **Lịch sử hội thoại:** người đã đăng nhập xem lại được trên mọi thiết bị; người ẩn danh chỉ trong phiên trình duyệt. Lưu mặc định 90 ngày, Organization chỉnh được. Quyền "xem hội thoại" tách riêng khỏi quyền quản trị. | 1 |
| D14 | **Chuyển sang người thật:** MVP chỉ ở mức tối giản (thông tin liên hệ, gửi bản ghi hội thoại qua email/webhook). Không tự xây hộp thư chat trực tiếp; giai đoạn sau tích hợp với hệ thống CSKH khách đang dùng. | 1 |
| D15 | **Chống lạm dụng chế độ ẩn danh:** giới hạn tần suất, trần chi phí theo ngày cho từng Channel (bật mặc định), captcha chống bot tự host được (tùy chọn), giới hạn phạm vi chủ đề trong Instructions. | 1 |
| D16 | **Appearance:** Theme Organization → Channel ghi đè **từng thuộc tính** (có nhãn Kế thừa/Đã ghi đè, nút khôi phục). Thuộc tính MVP: màu chủ đạo, font trong danh sách an toàn, bo góc, vị trí launcher, icon/avatar, tên hiển thị, kích thước, sáng/tối/tự động (kèm hàm `setTheme`), ngôn ngữ giao diện. Kiểm tra tương phản WCAG AA. Giao diện áp dụng ngay khi lưu, không quản lý phiên bản. Branding trang quản trị để giai đoạn sau. | 1 |
| D17 | **Model cloud:** chỉ theo hình thức khách tự mang key (BYOK), bên mình không bán lại token trong MVP. Công tắc "Cho phép model cloud" cấp Organization, **mặc định tắt**. Collection có cờ "Chỉ model local" — không gắn được vào Assistant dùng model cloud. Mọi lần chuyển sang model cloud đều có cảnh báo và audit. | 1 |
| D18 | **Phiên bản model:** mỗi Assistant ghim một phiên bản model cụ thể; bên vận hành không bao giờ tự đổi model dưới một Assistant; ngừng hỗ trợ phải báo trước tối thiểu 30 ngày. Khi lỗi: thử lại một lần rồi báo lỗi thân thiện; **không bao giờ fallback từ local sang cloud**. | 1 |
| D19 | **Instructions:** biểu mẫu có cấu trúc (Vai trò, Phạm vi, Điều không được làm, Giọng điệu, Ngôn ngữ, Khi không biết) kèm ô nâng cao. Ba tầng: guardrail nền tảng (không sửa được) → chính sách Organization → Instructions của Assistant. Tham số kỹ thuật ẩn sau 3 preset: Chính xác (mặc định) / Cân bằng / Sáng tạo. | 1 |
| D20 | **Phiên bản cấu hình:** cấu hình Assistant đi theo Draft → Publish, quay lại bản trước một thao tác; Channel chỉ chạy bản Published. Giao diện áp dụng ngay khi lưu. Tài liệu KB có hiệu lực ngay, không nằm trong bản chụp. | 1 |
| D21 | **Jev trong MVP:** dùng Jev (TypeSafe AI) để chọn kịch bản ngay từ MVP, dưới dạng tùy chọn: (1) tắt mặc định, bật hai lớp Organization → Assistant; (2) che dữ liệu cá nhân trước khi gửi; (3) bộ kịch bản "Chỉ model local" không đi qua Jev; (4) embedding + reranker local luôn là đường mặc định, Jev lỗi hoặc quá 800 ms thì rơi về local; (5) phát hành MVP không phụ thuộc việc có key Jev; (6) ngưỡng riêng cho từng nhà cung cấp, ghi nhà cung cấp vào từng tin nhắn; (7) spike đo chất lượng chạy song song. **Dùng key của nền tảng**, công bố TypeSafe là bên xử lý phụ, ký DPA trước khi bật cho khách thật — ngoại lệ của D17 chỉ áp dụng cho nhà cung cấp quyết định; nhà cung cấp sinh văn bản vẫn chỉ BYOK. | 1 |
| D22 | **So khớp kịch bản:** embedding + reranker (dùng chung với KB), 3 dải tin cậy — cao: trả kịch bản; trung bình: đưa cho LLM làm ngữ cảnh ưu tiên; thấp: đi luồng RAG. "Chọn kịch bản" là một Decision Provider có thể thay thế (local mặc định, Jev tùy chọn). | 1 |
| D23 | **Loại kịch bản MVP:** hỏi–đáp cố định, có biến từ token/session, hành động đơn giản (link, chuyển người thật). Luồng nhiều bước để sang Skills. | 1 |
| D24 | **Vòng đời kịch bản:** nội dung có hiệu lực ngay; từng kịch bản có trạng thái Nháp / Đang dùng / Tắt và ngày hết hạn tùy chọn; bản chụp Publish của Assistant chỉ giữ danh sách bộ kịch bản được gắn (làm rõ D20). | 1 |
| D25 | **Ưu tiên kịch bản:** mặc định trả nguyên văn (tùy chọn cho diễn đạt lại); kịch bản thắng khi mâu thuẫn với KB; thiếu ngôn ngữ người dùng thì hạ xuống dải trung bình. | 1 |
| D26 | **Pipeline xử lý câu hỏi 5 bước:** [1] Gate (luật, local: giới hạn tần suất, chuẩn hóa, nhận diện ngôn ngữ, che dữ liệu cá nhân, guardrail đầu vào) → [2] Classifier (phân loại câu hỏi) → [3] Script Matcher (có trong kịch bản không) → [4] Orchestrator (chọn KB/Tool/Skill, soạn câu trả lời) → [5] Response Guard (trích dẫn, lọc hiển thị, ngôn ngữ, ghi trace từng bước). **Jev chỉ nằm ở bước [3].** Bước [2], phần lọc ứng viên của [3] và truy xuất KB chạy song song. | 1 |
| D27 | **Classifier:** chạy hoàn toàn local, đọc 2 lượt hội thoại gần nhất. 7 loại: `chao_hoi`, `chuyen_nguoi`, `ngoai_pham_vi` (chỉ khi tin cậy rất cao, chỉ yêu cầu ngoài phạm vi phổ quát), `tiep_noi` (bỏ qua Script Matcher), `thong_tin` (**mặc định khi không chắc**), `tac_vu` và `du_lieu` (MVP xử lý như `thong_tin`). MVP: luật + embedding so với câu mẫu; giai đoạn sau có thể fine-tune Laya một lần cho cả nền tảng. | 1 |
| D28 | **Orchestrator kiểu lai:** khung ngoài cố định theo loại câu hỏi; chỉ bên trong nhánh Skill/Connector mới cho LLM chọn Tool, trong danh sách Tool được phép, có giới hạn số bước. MVP tìm trên tất cả Collection gắn với Assistant (đã lọc quyền); chọn Collection theo mô tả để giai đoạn sau. | 1 |
| D29 | **Tối thiểu hóa dữ liệu gửi Jev** (bổ sung D21): chỉ gọi Jev khi embedding đã tìm được ứng viên kịch bản đủ gần; chỉ gửi tin nhắn hiện tại đã che dữ liệu cá nhân cùng danh sách ứng viên, không gửi lịch sử hội thoại. | 1 |
| D30 | **Spike Jev:** so Jev với reranker local ở Script Matcher; cùng bộ câu test được gắn thêm nhãn loại câu hỏi để đo Classifier local. Kế hoạch: [jev-spike.md](jev-spike.md). | 1 |
| D31 | **Lát mỏng Skills/Connector trong MVP:** Connector kiểu HTTP API + Tool **chỉ đọc** (khai báo thủ công hoặc import OpenAPI) + Skill **kiểu cố định** (hỏi đủ thông tin → gọi Tool → trả lời theo mẫu). Orchestrator chọn Skill theo mô tả "khi nào dùng"; không chọn được thì rơi về `thong_tin`. Playground chạy với token người dùng thử. | 1 |
| D32 | **Nguyên tắc danh tính cho Tool:** tham số về danh tính và quyền chỉ được gắn từ token đã ký (D11); LLM không bao giờ thấy hay điền được. Ưu tiên chuyển tiếp token để app chủ tự kiểm tra quyền. Không có Tool/Connector ở chế độ ẩn danh. | 1 |
| D33 | **Kết nối ở chế độ tập trung:** giai đoạn đầu chỉ API HTTPS mà server trung tâm gọi tới được (khách giới hạn theo IP, có xác thực). Khách chỉ có app trong mạng nội bộ dùng bản tự host. Connector agent (tự mở kết nối ra ngoài) để giai đoạn sau. Mọi lời gọi ra ngoài đi qua proxy đầu ra có danh sách domain được phép theo Workspace. | 1 |
| D34 | **Truy cập dữ liệu:** ưu tiên API. DB chỉ qua truy vấn dựng sẵn có tham số trên tài khoản chỉ đọc (giai đoạn sau). **Không** làm text-to-SQL cho người dùng cuối. Tool ghi để giai đoạn sau và bắt buộc người dùng xác nhận bằng thẻ trong widget, có audit. | 1 |
| D35 | **Định dạng Skill:** bán cấu trúc (tên, mô tả khi nào dùng, thông tin cần hỏi, các bước bằng ngôn ngữ tự nhiên, Tool được phép, cờ cần xác nhận, mẫu trả lời); Skill nằm trong bản chụp Publish. Hai kiểu chạy: cố định (MVP) và linh hoạt (giai đoạn sau, chỉ với model có nhãn "gọi tool"). MCP: bản tập trung chỉ cho MCP từ xa qua HTTP, bật riêng từng tool, mô tả tool coi là không đáng tin; giai đoạn sau. | 1 |
| D36 | **Memory không có trong MVP.** MVP dùng lịch sử hội thoại (D13), claim trong token, session variables và Tool — dữ liệu chính thức từ app thay cho điều AI tự ghi nhớ. | 1 |
| D37 | **Nguyên tắc Memory (giai đoạn sau):** chỉ ghi nhớ về từng người dùng, phạm vi (người dùng × Assistant), bật theo Assistant và tắt mặc định; người ẩn danh không có memory. Chỉ nhớ các loại khai báo sẵn (ngôn ngữ ưa thích, cách xưng hô, chủ đề quan tâm, vấn đề đang xử lý dở); không bao giờ nhớ dữ liệu nhạy cảm hay dữ liệu app đã cung cấp. Người dùng tự xem và xóa trong widget; quản trị viên không duyệt được memory từng người. Dữ liệu từ app luôn thắng memory. Rút trích chạy theo lô sau hội thoại. | 1 |
| D38 | **Không bao giờ có ghi nhớ chung tự học từ hội thoại.** Mọi việc học chung đi qua vòng có người duyệt (câu hỏi chưa trả lời được → biên tập viên bổ sung tài liệu hoặc kịch bản). | 1 |
| D39 | **Schedule không là module riêng**, mà là thuộc tính thời gian của từng tính năng: MVP có ngày bắt đầu/kết thúc cho kịch bản; đồng bộ nguồn tri thức định kỳ và báo cáo định kỳ cho chủ workspace để giai đoạn sau. **Không làm** tác vụ agent chạy định kỳ và không chủ động nhắn người dùng. | 1 |
| D40 | **Bổ sung MCP:** lưu mô tả và tham số tool lúc duyệt, tự tắt tool khi MCP server thay đổi chúng cho đến khi duyệt lại; xác thực OAuth/API key; MCP tuân theo mọi quy tắc của Connector (D32, D33). "ei-ai làm MCP server" ghi nhận là một Channel cho giai đoạn sau. | 1 |
| D41 | **Knowledge Graph không vào MVP và không vào giai đoạn 2.** Chỉ xét lại khi analytics và bộ đo cho thấy câu hỏi quan hệ nhiều bước hoặc câu hỏi tổng quát chiếm trên 10–15% số câu chưa trả lời được (con số cần chốt), và các giải pháp rẻ hơn (D43, D44) đã được thử. | 1 |
| D42 | **Nếu làm KG sau này:** chỉ dạng chỉ mục đồ thị nội bộ cho bước truy xuất, bật theo Collection, mang quyền truy cập của tài liệu nguồn (D8), không có trình biên tập graph. Ontology dựng tay và hiển thị trực quan: không khuyến nghị. Node business logic gộp vào Skills (D35). | 1 |
| D43 | **Từ điển thuật ngữ theo Workspace trong MVP:** từ viết tắt, từ đồng nghĩa, tên cũ/mới, song ngữ; dùng ở truy xuất, Classifier và Script Matcher. | 1 |
| D44 | **Giai đoạn sau:** metadata tài liệu với bộ lọc (dòng sản phẩm, phòng ban, chi nhánh, ngày hiệu lực), tóm tắt phân cấp cho câu hỏi tổng quát, mô tả Collection. Câu hỏi chưa trả lời được được gắn nhãn nguyên nhân (thiếu tài liệu, viết tắt, quan hệ nhiều bước, câu hỏi tổng quát) để làm bằng chứng cho D41. | 1 |
| D45 | **Khép Co-work:** chọn file/folder theo từng hội thoại (chỉ người đã đăng nhập) và AI gợi ý tổ chức KB (phát hiện trùng, lỗi thời, mâu thuẫn; gợi ý folder/tag; **người duyệt từng gợi ý**) để giai đoạn sau. Bỏ hẳn thuật ngữ "Co-work". | 1 |
| D46 | **Cách ly tenant hai lớp:** dùng chung DB, mọi bảng có `org_id`, DB tự áp quy tắc cách ly theo dòng (ví dụ Row-Level Security) bên cạnh code ứng dụng; chỉ mục vector tách theo Organization; file gốc trong thư mục riêng, mỗi Organization một khóa mã hóa riêng (hủy khóa khi xóa); tenant chỉ lấy từ thông tin xác thực đã kiểm tra, không bao giờ từ tham số request; bộ test cách ly tự động trong CI, phủ cả đường phụ (job nền, export, cache, webhook). DB hoặc bản cài riêng cho khách lớn để giai đoạn sau. | 2 |
| D47 | **Vị trí đặt server trung tâm:** hoãn — tùy theo từng khách. Mục tiêu hiện tại là có sản phẩm thử. Điều kiện: chốt vị trí và tư vấn pháp lý (Luật Bảo vệ dữ liệu cá nhân, Nghị định 53/2022, hồ sơ chuyển dữ liệu ra nước ngoài khi bật Jev) **trước khi có khách trả tiền đầu tiên**. | 2 |
| D48 | **RBAC ba tầng**, vai trò cố định trong MVP. Nền tảng: Platform Admin, Platform Support, Billing (không đọc dữ liệu khách khi chưa được cấp quyền). Organization: Org Owner, Org Admin (không tự động đọc hội thoại). Workspace: Workspace Admin, Developer, Builder, Knowledge Editor, Reviewer, Viewer. Ba quyền nhạy cảm tách riêng: đọc hội thoại (Reviewer), quản lý secret/Connector (Developer), Publish (Builder). Đổi phân quyền Collection chỉ Workspace Admin làm được. Tự định nghĩa vai trò để giai đoạn sau. | 2 |
| D49 | **Đăng nhập quản trị:** email + mật khẩu; bắt buộc 2FA (TOTP) cho Org Owner, Org Admin, Developer và mọi vai trò tầng nền tảng. SSO (OIDC/SAML) và API key để giai đoạn sau. | 2 |
| D50 | **Audit log trong MVP:** ghi mọi thao tác quản trị (không ghi từng tin nhắn chat), gồm cả các lần nhân sự nền tảng truy cập hỗ trợ — khách nhìn thấy được; chỉ ghi thêm; giữ mặc định 1 năm, xuất CSV. **Vòng đời tenant:** Platform Operator tạo Organization; tạm ngưng giữ nguyên dữ liệu; xóa có 30 ngày chờ rồi hủy khóa mã hóa và cấp xác nhận đã xóa; khách tự xuất dữ liệu để giai đoạn sau. | 2 |
| D51 | **Prompt injection — nguyên tắc "giới hạn thiệt hại":** chấp nhận chèn lệnh có lúc thành công. Bắt buộc từ ngày đầu: (1) giới hạn khả năng của LLM (D2, D32, D33, D34), (2) tách lệnh và dữ liệu trong prompt, (3) lọc đầu ra (P24). Trong MVP: chuỗi canary trong system prompt, sàng lọc đầu vào ở Gate (chỉ ghi log, không chặn), quét tài liệu khi nạp (gắn cờ cho biên tập viên). Bộ test tấn công song ngữ có trước khi khách thật dùng. | 2 |
| D52 | **Dữ liệu cá nhân:** nhật ký hội thoại lưu nguyên văn, mã hóa theo khóa Organization, quyền xem theo D48. Trace và log hệ thống **luôn che** dữ liệu cá nhân, che ở tầng thư viện ghi log. Chức năng "xóa mọi dữ liệu của người dùng X" (theo user ID trong token) có trong MVP, có audit. | 2 |
| D53 | **Che dữ liệu cá nhân theo nhà cung cấp:** Jev luôn được che (D29). Model cloud do khách tự bật (D17) **không che**; màn hình bật cloud ghi rõ điều này. | 2 |
| D54 | **Hạng mục pháp lý hoãn, bổ sung sau:** vai trò bên xử lý dữ liệu, mẫu DPA, danh sách bên xử lý phụ, quy trình thông báo vi phạm, pentest, link chính sách quyền riêng tư và banner xin đồng ý trong widget. Gắn với câu hỏi mở O7. | 2 |
| D55 | **Công tắc khẩn cấp trong MVP**, có audit: tắt Channel; tắt Tool/Connector (Skill rơi về `thong_tin`); tắt cloud và Jev của Organization; quay lại bản Assistant trước (D20); tắt Jev toàn nền tảng (Platform Admin). | 2 |
| D56 | **Chất lượng AI:** bộ đo ba tầng — nền tảng (dữ liệu giả, có thể dùng model cloud làm giám khảo), từng khách (30–50 câu lúc onboarding, chấm bằng chỉ số không cần LLM; giám khảo cloud chỉ khi Organization đã bật cloud), từng Skill (có câu cố tình lừa). Chỉ số: hit@k, có trích dẫn, trích dẫn hợp lệ, từ chối đúng, bám tài liệu (chỉ ở tầng nền tảng). Response Guard kiểm tra trích dẫn phải thuộc các đoạn đã truy xuất. Từ bản thử: ghi chi tiết truy xuất vào trace; thu phản hồi 👍/👎 kèm lý do. | 2 |
| D57 | **Hiệu năng** (đo trên cấu hình tham chiếu, điều chỉnh sau khi đo): khớp kịch bản local p95 < 1 s; qua Jev < 1,5 s; RAG tới chữ đầu tiên < 3 s, trả lời xong < 15 s; Skill gọi Tool < 10 s. Quá tải thì báo bận ngay. Ngân sách ngữ cảnh: chỉ dẫn ~1.000 token, 3–5 đoạn tài liệu, 2–4 lượt hội thoại, kết quả Tool chỉ trường cần thiết. | 2 |
| D58 | **Không cache câu trả lời theo nghĩa** trong MVP (người dùng có quyền khác nhau; tài liệu có hiệu lực ngay). **Đo mức sử dụng chi tiết từ bản thử** (tin nhắn, token theo model, trang đã nạp, dung lượng, lời gọi Tool, lời gọi Jev — theo Organization, Assistant, Channel); chặn quota ở bản thử làm đơn giản. | 2 |
| D59 | **Observability:** trace từng tin nhắn có dấu phiên bản (Assistant, model, nhà cung cấp Script Matcher, kịch bản, Tool) từ bản thử. Bản thử: dashboard cơ bản + danh sách câu chưa trả lời được. MVP: cảnh báo, analytics đầy đủ cho khách. Xuất/nhập cấu hình dạng file để giai đoạn sau. | 2 |
| D60 | **Tiếng Việt:** chuẩn hóa Unicode (NFC và kiểu đặt dấu thanh) ở lúc nạp tài liệu và ở Gate, và chỉ mục bỏ dấu cho tìm theo từ khóa — **bắt buộc từ ngày đầu**. Cách tách từ chọn bằng bộ đo. Câu trộn Việt–Anh đưa vào bộ đo. Thêm ô "Cách xưng hô" vào biểu mẫu Instructions (D19). Nhãn "Tiếng Việt" trong danh mục model gắn theo kết quả đo. | 2 |
| D61 | **Phạm vi bản thử** như mục 6 của [tong-hop.md](tong-hop.md): đủ nền móng F1–F15; KB có phân quyền; widget có token ký; pipeline 5 bước; kịch bản; một Connector + một Skill tra cứu. | 4 |
| D62 | **Thứ tự xây dựng** M0 → M5 như mục 9 của tổng hợp; Jev tách riêng thành M3b, làm khi có key. | 4 |
| D63 | **Khách thử nghiệm:** demo nội bộ với doanh nghiệp giả định và một app giả có API tra cứu đơn hàng; sau đó một khách thử nghiệm thật có API gọi được từ bên ngoài, đồng ý bằng văn bản về dữ liệu, thuộc một ngành cụ thể. | 4 |
| D64 | **Tự xây lõi, dùng lại thư viện mã nguồn mở** (đọc file, chỉ mục, phục vụ model); không dựa trên một nền tảng hoàn chỉnh. Kiểm tra ngắn 1–2 ngày về thư viện dùng lại được và giấy phép trước khi chốt hẳn. | 4 |
| D65 | **Giai đoạn thiết kế bắt đầu bằng thiết kế giao diện**, dùng giao diện để kiểm tra/hình dung ý tưởng và xác định hướng làm; tech stack, kiến trúc và mô hình dữ liệu làm sau. | 4 |
| D66 | **Doanh nghiệp giả định đổi thành công ty công nghệ làm outsource** (Mekong Devworks, quản lý đội software engineer) thay cho cửa hàng điện máy; Skill mẫu là "Check my leave balance" qua HR System API thay cho tra cứu đơn hàng (cập nhật D63). Các quyết định thiết kế giao diện ghi riêng ở [design-decisions.md](../design/design-decisions.md). | 4 |
| D67 | **Chat trực tiếp trên console** — bề mặt thứ hai bên cạnh widget, cùng pipeline (mở rộng D2, D5; yêu cầu của chủ dự án 2026-10-13, WGT-12/EA-88). Thành viên đã đăng nhập console có trang **Chat** để hỏi Assistant ngay trên web. (1) Mọi vai trò Workspace đều dùng được; thêm vai trò **Member** chỉ thấy Chat (bổ sung D48). (2) Nhóm quyền tri thức (D8) do Org Admin gán cho từng thành viên ở Members & roles, lưu phía server; sau này lấy từ claim SSO/OIDC. (3) Danh tính cho Skill: trường **External user ID** của từng thành viên, server gắn vào token nội bộ, LLM không thấy (giữ D32). (4) Mỗi Workspace có sẵn một **Channel nội bộ "Console chat"** (không xóa được, không có mã nhúng), nên dùng lại giới hạn tần suất, lưu 90 ngày (D13), công tắc khẩn cấp (D55), đo sử dụng (D58) và trang Conversations. (5) Danh sách chọn Assistant: chỉ bản Published được bật cho Console chat và nhóm của người dùng được phép; bản Draft dùng Playground. (6) Reviewer chỉ mở được hội thoại Console chat có 👍/👎, mỗi lần mở ghi audit (D50); câu chưa trả lời được vẫn vào Unanswered. (7) Thuộc bản thử, làm sau M2. | 4 |

---

## 3. Phản biện và hướng xử lý

### 3.1 Định vị và cạnh tranh

**P1. Phần lõi là "hàng phổ thông"** — [Nội bộ]
- *Vấn đề:* Knowledge Base + widget nhúng + self-hosted + model local đã là tính năng tiêu chuẩn của các nền tảng mã nguồn mở như Dify, MaxKB, AnythingLLM, FastGPT, RAGFlow. Câu khách hàng sẽ hỏi đầu tiên: "sao không cài Dify?".
- *Hướng xử lý:* khác biệt phải nằm ở nghiệp vụ + dữ liệu sống của app + trải nghiệm cho người không biết kỹ thuật + tiếng Việt (D3). MVP vẫn là phần phổ thông, nên Skills và Data Connector phải được đưa vào sớm ngay sau MVP.
- *Trạng thái:* đã chốt định vị (D3). Còn mở: spike 1–2 tuần dựng thử các nền tảng trên để xác định phần nào không nên tự đầu tư.

**P2. Giấy phép mã nguồn mở là ràng buộc thật** — [Nội bộ]
- *Vấn đề:* Dify dùng Apache-2.0 có điều khoản bổ sung, hạn chế vận hành multi-tenant (Dify định nghĩa 1 workspace = 1 tenant) và cấm gỡ logo ở frontend nếu không có giấy phép thương mại. MaxKB là GPL-3.0 (copyleft). AnythingLLM là MIT; RAGFlow là Apache-2.0.
- *Hệ quả:* một sản phẩm thương mại "nhiều workspace, tùy biến giao diện" va thẳng vào điều khoản của Dify.
- *Trạng thái:* cần xác minh lại bản giấy phép mới nhất trước khi quyết định xây trên nền có sẵn hay tự xây lõi.

**P3. "Tất cả công ty và cá nhân có website" không phải tệp khách hàng mục tiêu** — [Nội bộ]
- *Vấn đề:* cá nhân hiếm khi có server GPU, nhiều SMB cũng chưa có.
- *Trạng thái:* phần nào được giải quyết bởi D1 (bản cài tập trung không đòi khách có GPU). Vẫn nên chọn 1–2 ngành mục tiêu cho giai đoạn đầu.

### 3.2 Triển khai và hạ tầng

**P4. "Self-hosted nội bộ" mâu thuẫn với "nhúng widget vào website công khai"** — [Nội bộ]
- *Vấn đề:* nếu widget nằm trên website công khai, người dùng từ internet phải gọi được tới backend, nên hệ thống không còn thuần nội bộ.
- *Hướng xử lý:* cần một lớp phơi ra ngoài (reverse proxy/DMZ), chống lạm dụng, tách tri thức công khai và nội bộ. D2 giới hạn chế độ ẩn danh để giảm bề mặt tấn công.

**P5. "< 500 user" chưa rõ đếm ai** — [Nội bộ]
- *Vấn đề:* với LLM local, thứ quyết định phần cứng là số phiên chat đồng thời, không phải số tài khoản.
- *Trạng thái:* tạm gác cho MVP (D2). Phải trả lời trước khi định cỡ hạ tầng production.

**P6. Model local mặc định so với các tính năng cần model mạnh** — [Nội bộ]
- *Vấn đề:* Agent, gọi Tool và trích xuất Knowledge Graph phụ thuộc mạnh vào cỡ model. Rủi ro điển hình: demo bằng GPT/Claude chạy tốt, triển khai trên model local thì hỏng.
- *Hướng xử lý:* cấu hình tham chiếu + mỗi tính năng ghi rõ yêu cầu tối thiểu + chế độ lai (tài liệu và embedding luôn local, chỉ bước sinh câu trả lời ra cloud nếu quản trị bật) — D4.

**P7. Vận hành tập trung mâu thuẫn với "chạy hoàn toàn nội bộ"** — [Nội bộ]
- *Vấn đề:* ở chế độ tập trung, dữ liệu khách nằm trên server của nhà cung cấp; giữ câu định vị cũ dễ bị xem là quảng cáo sai.
- *Trạng thái:* đã sửa câu định vị (mục 1, D6).

**P8. Vận hành tập trung làm khó việc "đọc dữ liệu app của khách"** — [Nội bộ]
- *Vấn đề:* app của khách thường nằm trong mạng nội bộ của họ; server trung tâm không gọi vào được.
- *Hướng khả dĩ:* (a) khách mở API ra internet; (b) VPN; (c) connector agent nhỏ cài phía khách, tự mở kết nối ra ngoài nên khách không phải mở cổng vào trong.
- *Trạng thái:* **còn mở** — rủi ro kiến trúc lớn nhất của D1 + D3, sẽ xử lý ở module Data Connector.

**P9. Nhiều tenant dùng chung model local** — [Nội bộ]
- *Vấn đề:* một tenant dùng quá tải làm chậm tất cả các tenant khác; cache dùng chung có thể rò dữ liệu chéo.
- *Hướng xử lý:* giới hạn số yêu cầu đồng thời theo tenant; mọi cache tách theo tenant; xử lý tài liệu theo hàng đợi chia đều.

**P10. Dev trên phần cứng yếu dễ dẫn tới đánh giá sai** — [Nội bộ]
- *Vấn đề:* model nhỏ khiến team lúc tưởng tính năng không khả thi, lúc tưởng đã đủ tốt; prompt bị chỉnh quá sát model nhỏ.
- *Hướng xử lý:* các điều kiện của D4. Kết quả kiểm tra máy dev: xem mục 6.

### 3.3 Khái niệm và phạm vi

**P11. Mười module chồng chéo nhau** — [Nội bộ]
- *Vấn đề:* có ba nơi cùng cấu hình "hành vi AI" (Instructions, User Manual, Business Logic); "Co-work" mang hai nghĩa khác nhau; Module 10 lặp lại các module khác.
- *Trạng thái:* đã gom về khoảng 6 khái niệm lõi (D5, bảng thuật ngữ ở mục 5).

**P12. Jev và Laya-MLX lệch ràng buộc nền** — [Nội bộ]
- *Vấn đề:* Jev là dịch vụ cloud đang early access; Laya-MLX chỉ chạy trên Apple Silicon — hiếm khi là server doanh nghiệp.
- *Trạng thái:* chưa khuyến nghị cho MVP. Sẽ đánh giá chi tiết ở module Answer Scripts.

**P13. Knowledge Graph đang gộp ba thứ khác nhau** — [Nội bộ]
- *Vấn đề:* (i) chỉ mục đồ thị tự trích xuất để truy xuất tốt hơn, (ii) mô hình nghiệp vụ dựng tay, (iii) cách hiển thị memory. Mỗi thứ có chi phí và giá trị khác nhau.
- *Trạng thái:* ra khỏi MVP; chỉ xét lại khi có bằng chứng RAG thuần thất bại ở câu hỏi quan hệ hoặc nhiều bước.

### 3.4 Knowledge Base — chất lượng, bảo mật, dữ liệu

**P14. Không thể trông chờ LLM tự giấu thông tin** — [Đối ngoại được, khi đã triển khai]
- *Vấn đề:* nếu tài liệu người dùng không được xem lọt vào ngữ cảnh, LLM có thể tiết lộ nó.
- *Hướng xử lý:* lọc theo quyền **trước khi** truy xuất (D8), có test tự động cho phân quyền.
- *Thông điệp đối ngoại gợi ý:* "Trợ lý chỉ đọc được những tài liệu mà chính người hỏi được phép xem."

**P15. Rò dữ liệu chéo giữa các khách hàng** — [Đối ngoại được, khi đã triển khai]
- *Hướng xử lý:* chỉ mục tách riêng cho từng Organization (không chỉ dựa vào bộ lọc), mã hóa file gốc khi lưu, cache tách theo tenant, khi khách rời đi thì xuất dữ liệu cho họ rồi xóa toàn bộ.

**P16. Nhân sự nhà cung cấp là một mối đe dọa phải tính đến** — [Đối ngoại được, khi đã triển khai]
- *Hướng xử lý:* mặc định không truy cập dữ liệu khách; quyền hỗ trợ do khách cấp, có thời hạn, ghi audit (D6).

**P17. AI bịa thông tin** — [Đối ngoại được, khi đã triển khai]
- *Hướng xử lý:* chế độ chặt bật mặc định (chỉ trả lời từ tri thức đã có); mọi câu trả lời dựa trên tài liệu đều có trích dẫn; không tìm thấy thì nói "không tìm thấy" và ghi vào danh sách câu hỏi chưa trả lời được.

**P18. Xóa tài liệu nhưng AI vẫn trả lời bằng nội dung cũ** — [Đối ngoại được, khi đã triển khai]
- *Hướng xử lý:* xóa phải xóa đến tận cùng — file gốc, các đoạn đã chia, vector, cache; backup có chính sách hết hạn. Liên quan Luật Bảo vệ dữ liệu cá nhân (hiệu lực 01/01/2026).

**P19. Khách kỳ vọng AI tính toán trên Excel** — [Nội bộ; đưa vào hợp đồng]
- *Vấn đề:* RAG lấy về các đoạn văn bản rời rạc nên không cộng dồn đúng trên cả bảng; để LLM tự tính sẽ ra số sai mà trông rất thuyết phục.
- *Trạng thái:* D10 — chỉ tra cứu; nói rõ giới hạn trong UI và hợp đồng.

**P20. File upload là bề mặt tấn công** — [Nội bộ]
- *Vấn đề:* macro trong Office, file nén khổng lồ khi giải nén, lỗ hổng trong thư viện đọc file, lệnh ẩn nhắm vào AI (prompt injection) trong nội dung tài liệu.
- *Hướng xử lý:* xử lý file trong môi trường cô lập, giới hạn kích thước và thời gian; coi nội dung tài liệu là dữ liệu, không phải lệnh — đặc biệt khi đã có Tool.

**P21. Hỏi một ngôn ngữ, tài liệu ở ngôn ngữ khác** — [Đối ngoại được, khi đã triển khai]
- *Hướng xử lý:* embedding đa ngôn ngữ để tìm chéo Việt–Anh; kết hợp tìm theo từ khóa để không bỏ sót mã sản phẩm, số hiệu văn bản.

### 3.5 Chatbot Widget — định danh, an toàn hiển thị, lạm dụng

**P22. Người dùng tự xưng là người khác** — [Đối ngoại được, khi đã triển khai]
- *Vấn đề:* nếu website chủ truyền user ID bằng JavaScript không ký, ai cũng có thể sửa để đọc tài liệu Restricted của người khác; toàn bộ D8 vô hiệu.
- *Hướng xử lý:* D11 — chỉ backend của khách giữ khóa ký; nhóm người dùng chỉ lấy từ token đã ký.
- *Thông điệp đối ngoại gợi ý:* "Danh tính người dùng do chính hệ thống của bạn xác nhận; trợ lý không tin bất kỳ thông tin nào trình duyệt tự khai."

**P23. Danh sách domain được phép không phải là lớp bảo vệ thật** — [Nội bộ; ghi rõ trong tài liệu tích hợp]
- *Vấn đề:* header Origin có thể bị giả mạo khi gọi từ ngoài trình duyệt; danh sách domain chỉ ngăn site khác nhúng lại widget.
- *Hướng xử lý:* bảo vệ thật nằm ở token đã ký (chế độ đăng nhập) và giới hạn tần suất (chế độ ẩn danh). Nói rõ với khách để họ không bỏ qua các lớp khác.

**P24. Câu trả lời của AI có thể làm rò dữ liệu** — [Nội bộ]
- *Vấn đề:* lệnh ẩn trong tài liệu có thể khiến AI sinh markdown chứa ảnh trỏ tới địa chỉ bên ngoài, nhét dữ liệu nhạy cảm vào URL; trình duyệt tải ảnh là dữ liệu bị gửi đi. Ngoài ra còn nguy cơ XSS nếu hiển thị HTML thô.
- *Hướng xử lý:* lọc sạch HTML; mặc định không tải ảnh từ domain ngoài; đánh dấu rõ link ra ngoài.

**P25. Chế độ ẩn danh bị dùng để đốt chi phí** — [Nội bộ]
- *Vấn đề:* kẻ xấu gửi hàng loạt câu hỏi để đốt quota của khách; nếu Organization đã bật model cloud thì phát sinh hóa đơn thật.
- *Hướng xử lý:* D15 — trần chi phí theo ngày cho từng Channel bật mặc định, giới hạn tần suất, captcha tùy chọn.

**P26. Người dùng ẩn danh dùng trợ lý như ChatGPT miễn phí** — [Nội bộ]
- *Hướng xử lý:* giới hạn phạm vi chủ đề trong Instructions (D15); giai đoạn sau thêm bộ lọc câu hỏi lạc đề.

**P27. Hộp thư chat trực tiếp là cả một sản phẩm riêng** — [Nội bộ]
- *Vấn đề:* tự xây hộp thư CSKH (kiểu Chatwoot) tốn nhiều tháng mà không tạo khác biệt; khách thường đã có hệ thống CSKH.
- *Trạng thái:* D14 — chỉ chuyển tiếp tối giản.

**P28. Thời gian chờ của model local** — [Nội bộ]
- *Vấn đề:* trên phần cứng yếu, chữ đầu tiên có thể mất hàng chục giây; người dùng tưởng widget bị treo.
- *Hướng xử lý:* câu trả lời hiện dần (streaming), hiển thị trạng thái từng bước, cho phép bấm dừng.

**P29. Khách không tự tích hợp được** — [Nội bộ]
- *Vấn đề:* bước ký token ở backend là rào cản lớn nhất với lập trình viên của khách.
- *Hướng xử lý:* tài liệu kèm ví dụ ký token cho Node, PHP, .NET, Java, Python; trang kiểm tra tích hợp (dán token để biết chữ ký đúng chưa, hết hạn chưa, nhóm có khớp không).

**P30. Không thể dựa vào cookie trong iframe** — [Nội bộ]
- *Vấn đề:* Safari và Firefox mặc định chặn cookie bên thứ ba trong iframe; website chủ có thể có CSP chặn script và iframe từ domain lạ.
- *Hướng xử lý:* D12 — truyền token qua postMessage; tài liệu tích hợp ghi rõ cần thêm gì vào CSP.

### 3.6 Appearance

**P31. "Giao diện toàn hệ thống" gộp hai nghĩa khác nhau** — [Nội bộ]
- *Vấn đề:* (a) theme mặc định cho widget; (b) branding trang quản trị cho khách/đối tác bán lại.
- *Trạng thái:* D16 — MVP chỉ làm (a); (b) để giai đoạn sau, gắn với chính sách đối tác.

**P32. Lỗi nhỏ nhưng gây phiền ở Appearance** — [Nội bộ]
- *Vấn đề:* màu thương hiệu nhạt khiến chữ khó đọc; cache CDN khiến khách lưu rồi không thấy thay đổi; SVG upload có thể chứa mã độc.
- *Hướng xử lý:* kiểm tra tương phản; làm mới cache khi lưu; lọc SVG hoặc chuyển sang PNG.

### 3.7 AI Model Settings

**P33. Nâng cấp model làm hành vi trợ lý thay đổi ngầm** — [Đối ngoại được, khi đã triển khai]
- *Vấn đề:* ở chế độ tập trung, một lần nâng cấp model local ảnh hưởng mọi Assistant của mọi khách cùng lúc.
- *Hướng xử lý:* D18 — ghim phiên bản, báo trước 30 ngày, chạy bộ câu hỏi mẫu để so sánh trước khi chuyển.
- *Thông điệp đối ngoại gợi ý:* "Trợ lý của bạn không bao giờ bị đổi model mà bạn không biết."

**P34. Fallback tự động ra cloud vi phạm cam kết dữ liệu** — [Nội bộ]
- *Vấn đề:* nếu model local lỗi mà hệ thống tự chuyển sang cloud, dữ liệu đi ra ngoài đúng lúc hệ thống gặp sự cố — lúc không ai để ý.
- *Trạng thái:* D18 — không bao giờ fallback từ local sang cloud.

**P35. Tài liệu nhạy cảm đi ra cloud mà không ai nhận ra** — [Đối ngoại được, khi đã triển khai]
- *Hướng xử lý:* D17 — cloud tắt mặc định; cờ "Chỉ model local" theo Collection; cảnh báo và audit.
- *Thông điệp đối ngoại gợi ý:* "Bạn đánh dấu tài liệu nào là nhạy cảm, tài liệu đó không bao giờ được gửi tới model bên ngoài."

**P36. Bán lại token cloud kéo theo trách nhiệm pháp lý** — [Nội bộ]
- *Vấn đề:* khi bên mình cung cấp key cloud, bên mình thành bên xử lý dữ liệu thay khách và phải làm billing chuyển tiếp.
- *Trạng thái:* D17 — chỉ BYOK trong MVP.

**P37. Lộ API key của khách và lỗ hổng SSRF** — [Nội bộ]
- *Hướng xử lý:* mã hóa key khi lưu, không hiển thị lại (chỉ 4 ký tự cuối), chỉ quản trị Organization được sửa. Ở bản tập trung, builder không được tự nhập URL endpoint model (tránh server bị lợi dụng gọi vào địa chỉ nội bộ).

**P38. Builder sửa hỏng trợ lý đang phục vụ khách** — [Đối ngoại được, khi đã triển khai]
- *Hướng xử lý:* D20 — Draft → Publish, quay lại bản trước một thao tác.

**P39. Guardrail an toàn bị xóa nhầm; chất lượng phụ thuộc người viết prompt** — [Nội bộ]
- *Hướng xử lý:* D19 — ba tầng chỉ dẫn, guardrail nền tảng không sửa được; biểu mẫu có cấu trúc thay cho một ô văn bản tự do.

**P40. Cùng Instructions, khác model thì kết quả khác** — [Nội bộ]
- *Vấn đề:* bộ Instructions chạy tốt trên GPT có thể kém trên model local nhỏ; model nhỏ dễ "quên" chỉ dẫn khi ngữ cảnh dài.
- *Hướng xử lý:* bắt buộc chạy bộ câu hỏi mẫu khi đổi model; giữ tổng chỉ dẫn ngắn; ghi model, phiên bản, preset vào từng tin nhắn để truy vết.

### 3.8 Answer Scripts và Jev

**P41. Kịch bản là thông tin công khai, nhưng câu hỏi của người dùng thì không** — [Nội bộ]
- *Vấn đề:* để chọn kịch bản, thứ gửi sang Jev là **câu hỏi của người dùng**, không chỉ nội dung kịch bản. Câu hỏi có thể chứa dữ liệu cá nhân ("đơn 12345 của Nguyễn Văn A sao chưa giao?"), nhất là ở chế độ đăng nhập (D2). Server Jev đặt ở Mỹ.
- *Hướng xử lý:* tắt mặc định; che dữ liệu cá nhân trước khi gửi; bộ kịch bản gắn cờ "Chỉ model local" không đi qua Jev; công bố TypeSafe là bên xử lý phụ nếu dùng key của nền tảng.

**P42. Phụ thuộc dịch vụ early access** — [Nội bộ]
- *Vấn đề:* key cấp theo đợt, API và giá có thể đổi, dịch vụ có thể ngừng.
- *Hướng xử lý:* Jev không bao giờ là đường duy nhất. Đường mặc định là embedding + reranker chạy local; Jev lỗi hoặc quá thời gian thì tự rơi về local (chiều cloud → local không vi phạm D18). Ngày phát hành MVP không phụ thuộc việc có key Jev.

**P43. "Type-safe" không có nghĩa là đúng** — [Nội bộ]
- *Vấn đề:* Jev đảm bảo đầu ra là một nhãn hợp lệ, không đảm bảo đó là nhãn đúng; chưa có số liệu độc lập về tiếng Việt và độ tin cậy.
- *Hướng xử lý:* đo bằng bộ câu hỏi mẫu (có gõ không dấu và câu gần nghĩa khác ý); mỗi nhà cung cấp có ngưỡng riêng; ghi lại nhà cung cấp nào đã chọn kịch bản trong từng tin nhắn.

### 3.9 Pipeline xử lý câu hỏi

**P44. Gộp "phân loại câu hỏi" và "chọn kịch bản" vào một router** — [Nội bộ]
- *Vấn đề:* đề xuất router đơn ban đầu khiến mọi câu hỏi đi qua Jev và trộn hai trách nhiệm khác bản chất.
- *Trạng thái:* tách thành Classifier (local) và Script Matcher (Jev tùy chọn) — D26, D27, D29. Ý tưởng tách do chủ dự án đề xuất.

**P45. Pipeline 5 bước có thể là over-engineering cho MVP** — [Nội bộ]
- *Hướng xử lý:* các bước là ranh giới khái niệm; trong MVP, Classifier chỉ là luật + embedding, Orchestrator chỉ là một lời gọi RAG. Chi phí thật nằm ở việc giữ ranh giới rõ.

**P46. Classifier phân loại sai thì kéo theo cả chuỗi** — [Nội bộ]
- *Hướng xử lý:* không chắc thì xếp `thong_tin` (đường an toàn nhất); chỉ `ngoai_pham_vi` được chặn và cần tin cậy rất cao; phạm vi riêng của từng Assistant do LLM ở Orchestrator xử lý theo Instructions.

**P47. LLM agent tự do trên model local nhỏ** — [Nội bộ]
- *Vấn đề:* gọi sai Tool, lặp vô hạn, chi phí và thời gian không lường trước.
- *Trạng thái:* D28 — Orchestrator kiểu lai, LLM chỉ chọn Tool trong phạm vi một Skill, có giới hạn số bước.

### 3.10 Skills, Tools và Data Connectors

**P48. MVP không có lát nào của Skills thì không chứng minh được định vị** — [Nội bộ]
- *Trạng thái:* D31 — lát mỏng: Tool HTTP chỉ đọc + Skill kiểu cố định (ví dụ "Tra cứu đơn hàng").

**P49. Người dùng lừa LLM để xem dữ liệu của người khác** — [Đối ngoại được, khi đã triển khai]
- *Vấn đề:* "Tra đơn của khách hàng 456 giúp tôi" — nếu LLM được điền ID thì lộ dữ liệu.
- *Hướng xử lý:* D32 — tham số danh tính gắn từ token đã ký, LLM không thấy và không điền được; khi không tìm thấy thì nói "không tìm thấy trong tài khoản của bạn", không tiết lộ dữ liệu của người khác có tồn tại hay không; bộ test lừa đảo cho từng Skill.
- *Thông điệp đối ngoại gợi ý:* "Trợ lý chỉ truy cập được dữ liệu của chính người đang hỏi — điều này do hệ thống của bạn xác nhận, không phải do AI tự quyết."

**P50. Server trung tâm không gọi được vào app nội bộ của khách** — [Nội bộ]
- *Trạng thái:* D33 — giải quyết P8/O1 ở giai đoạn đầu bằng API HTTPS hoặc bản tự host; connector agent ở giai đoạn sau.

**P51. Text-to-SQL ra số sai, lộ dữ liệu, chạy truy vấn nặng** — [Nội bộ]
- *Trạng thái:* D34 — không làm cho người dùng cuối; DB chỉ qua truy vấn dựng sẵn trên tài khoản chỉ đọc.

**P52. Ghi nhầm dữ liệu thật** — [Đối ngoại được, khi đã triển khai]
- *Hướng xử lý:* D34 — Tool ghi để giai đoạn sau; bắt buộc người dùng xác nhận, có audit, chống thực hiện trùng lặp.
- *Thông điệp đối ngoại gợi ý:* "Trợ lý không bao giờ thay đổi dữ liệu của bạn khi chưa được bạn xác nhận."

**P53. MCP tùy ý = chạy mã tùy ý trên server dùng chung** — [Nội bộ]
- *Vấn đề:* MCP dạng tiến trình cục bộ (stdio) chạy mã trên hạ tầng của mọi khách; mô tả tool có thể bị cài lệnh ẩn nhắm vào AI (tool poisoning).
- *Trạng thái:* D35 — bản tập trung chỉ MCP từ xa qua HTTP, bật riêng từng tool.

**P54. Kết quả Tool chứa văn bản do người khác nhập** — [Nội bộ]
- *Vấn đề:* ghi chú đơn, tên sản phẩm có thể chứa lệnh ẩn nhắm vào AI.
- *Hướng xử lý:* kết quả Tool là dữ liệu, không phải lệnh; không bao giờ kích hoạt Tool ghi khi chưa có xác nhận; chỉ đưa các trường cần thiết vào LLM; secret không bao giờ vào prompt hay trace.

### 3.11 Memory, Schedule, MCP

**P55. Phần lớn nhu cầu "memory" đã có lời giải tốt hơn** — [Nội bộ]
- *Vấn đề:* app của khách đã biết người dùng là ai và có dữ liệu chính thức (gói dịch vụ, đơn hàng, ngôn ngữ). Memory tạo thêm một kho dữ liệu cá nhân mới với thông tin do AI suy luận, kém chính xác hơn.
- *Trạng thái:* D36 — không có memory trong MVP; D37 — khi làm thì phạm vi hẹp, dữ liệu app luôn thắng.

**P56. Ghi nhớ chung tự học bị "dạy sai"** — [Đối ngoại được, khi đã triển khai]
- *Vấn đề:* một người dùng nói "giá sản phẩm X là 10 triệu", trợ lý tự ghi nhớ rồi trả lời sai cho mọi người khác (memory poisoning).
- *Trạng thái:* D38 — không bao giờ tự học chung; mọi việc học chung có người duyệt.
- *Thông điệp đối ngoại gợi ý:* "Trợ lý không tự học từ người dùng. Mọi kiến thức mới đều do đội ngũ của bạn duyệt."

**P57. "Schedule" dễ kéo sản phẩm sang thị trường tự động hóa quy trình** — [Nội bộ]
- *Vấn đề:* tác vụ agent chạy định kỳ là lãnh địa của n8n/Zapier, đòi Tool ghi chạy không có người xác nhận — trái D34.
- *Trạng thái:* D39 — Schedule chỉ là thuộc tính thời gian; không làm tác vụ agent định kỳ.

**P58. MCP server "đổi ruột" tool sau khi đã được tin dùng** — [Nội bộ]
- *Vấn đề:* MCP server âm thầm đổi mô tả hoặc tham số tool, cài lệnh ẩn nhắm vào AI (rug pull).
- *Trạng thái:* D40 — lưu mô tả lúc duyệt, tự tắt tool khi có thay đổi.

### 3.12 Knowledge Graph và Co-work

**P59. Knowledge Graph gộp bốn thứ khác nhau** — [Nội bộ]
- *Vấn đề:* (i) chỉ mục đồ thị tự trích xuất, (ii) ontology dựng tay, (iii) hiển thị trực quan, (iv) node chứa business logic (trùng Skills).
- *Trạng thái:* D41, D42 — chỉ giữ khả năng (i) cho tương lai, có điều kiện.

**P60. Chi phí thật của KG lớn hơn vẻ ngoài** — [Nội bộ]
- *Vấn đề:* trích xuất bằng LLM qua mọi đoạn tài liệu và chạy lại khi tài liệu đổi; chất lượng kém trên model local, nhất là tiếng Việt; gộp thực thể khó; ontology dựng tay không ai bảo trì; thêm một hệ CSDL đồ thị; khó chứng minh hiệu quả. Trích xuất bằng model cloud nghĩa là gửi toàn bộ tài liệu ra ngoài — xung đột D17. Cạnh trong graph có thể làm lộ sự tồn tại của tài liệu Restricted.
- *Hướng xử lý:* các giải pháp rẻ hơn lấy phần lớn giá trị: từ điển thuật ngữ (D43), metadata, tóm tắt phân cấp (D44), Tool/Connector cho dữ liệu có cấu trúc (D31).

**P61. AI tự sắp xếp KB làm đổi phạm vi tri thức và quyền truy cập** — [Nội bộ]
- *Vấn đề:* di chuyển tài liệu giữa folder/Collection có thể làm Assistant đang chạy mất hoặc thêm tri thức, và đổi quyền theo D8, mà không ai biết.
- *Trạng thái:* D45 — AI chỉ gợi ý, người duyệt từng gợi ý.

### 3.13 Multi-tenancy, RBAC và audit (Vòng 2)

**P62. Cách ly tenant gần như không thể thêm sau khi đã có dữ liệu thật** — [Nội bộ]
- *Vấn đề:* chỉ dựa vào code ứng dụng thì một lần quên lọc `org_id` là rò dữ liệu giữa các khách; lỗi thường nằm ở đường phụ (job nền, export, cache, webhook, trang lỗi).
- *Trạng thái:* D46 — cách ly hai lớp và bộ test cách ly; phải chốt trước khi viết dòng code đầu tiên.

**P63. Xóa dữ liệu nhưng bản sao lưu vẫn còn** — [Đối ngoại được, khi đã triển khai]
- *Hướng xử lý:* D46, D50 — mỗi Organization một khóa mã hóa; hủy khóa thì cả file lẫn backup không đọc được nữa; cấp xác nhận đã xóa.
- *Thông điệp đối ngoại gợi ý:* "Khi bạn rời đi, dữ liệu của bạn bị xóa thật — kể cả trong bản sao lưu."

**P64. Vai trò gộp làm lộ secret hoặc hội thoại** — [Nội bộ]
- *Vấn đề:* một vai trò "Editor" chung khiến người dựng trợ lý thấy được secret kết nối vào app của khách hoặc đọc được hội thoại của người dùng.
- *Trạng thái:* D48 — tách ba quyền nhạy cảm; D49 — bắt buộc 2FA cho các vai trò giữ chìa khóa.

**P65. Hoãn quyết định vị trí server khi đã có sản phẩm thử** — [Nội bộ]
- *Vấn đề:* sản phẩm thử dễ trượt thành dùng dữ liệu thật của khách trước khi chốt vị trí server và nghĩa vụ pháp lý.
- *Hướng xử lý:* D47 — chốt trước khách trả tiền đầu tiên; giai đoạn thử dùng dữ liệu giả, hoặc dữ liệu của khách thử nghiệm có đồng ý bằng văn bản, hoặc triển khai tự host tại khách.

**P66. Nhân sự nội bộ lạm quyền** — [Đối ngoại được, khi đã triển khai]
- *Hướng xử lý:* D6, D48, D50 — mặc định không truy cập; quyền hỗ trợ do khách cấp; audit khách nhìn thấy được.
- *Thông điệp đối ngoại gợi ý:* "Mỗi lần nhân viên của chúng tôi truy cập để hỗ trợ, bạn đều thấy trong nhật ký của mình."

### 3.14 Bảo mật và quyền riêng tư (Vòng 2)

**P67. Không thể chặn prompt injection 100%** — [Nội bộ]
- *Vấn đề:* bộ lọc phát hiện chèn lệnh luôn có cách vượt qua; model local nhỏ còn dễ bị chèn lệnh hơn model cloud lớn vì kém tuân thủ chỉ dẫn hệ thống.
- *Trạng thái:* D51 — kiến trúc làm phần chính (LLM bị lừa hoàn toàn cũng không làm được gì nguy hiểm); bộ lọc chỉ là lớp phát hiện.

**P68. Dữ liệu cá nhân rò qua log** — [Nội bộ]
- *Vấn đề:* đội dev bật log chi tiết khi gỡ lỗi rồi quên tắt; dữ liệu cá nhân nằm trong log hệ thống ngoài mọi quy tắc phân quyền; log đã ghi thì không thu hồi được.
- *Trạng thái:* D52 — che ở tầng thư viện ghi log, không trông vào từng dev.

**P69. Che dữ liệu trong nhật ký hội thoại làm hỏng vòng cải tiến** — [Nội bộ]
- *Vấn đề:* Reviewer đọc "đơn `[MÃ]` của `[TÊN]`" thì không hiểu ngữ cảnh để cải thiện trợ lý.
- *Trạng thái:* D52 — lưu nguyên văn nhưng mã hóa theo Organization và giới hạn quyền xem. Đây là đánh đổi có chủ đích.

**P70. Hoãn hạng mục pháp lý** — [Nội bộ]
- *Vấn đề:* dễ ký khách đầu tiên mà chưa có DPA, quy trình thông báo vi phạm, hay pentest; khách vừa và lớn sẽ gửi phiếu đánh giá bảo mật.
- *Trạng thái:* D54 — hoãn theo quyết định của chủ dự án; gắn với O7 để không bị quên.

**P71. Không có cách tắt nhanh khi có sự cố** — [Đối ngoại được, khi đã triển khai]
- *Trạng thái:* D55 — công tắc khẩn cấp ở 5 phạm vi.
- *Thông điệp đối ngoại gợi ý:* "Khi có sự cố, bạn tắt được trợ lý, một tích hợp hay mọi kết nối ra bên ngoài chỉ bằng một thao tác."

### 3.15 Chất lượng, hiệu năng, observability, tiếng Việt (Vòng 2)

**P72. Có những thứ không thể thêm bù về sau** — [Nội bộ]
- *Vấn đề:* trace có dấu phiên bản, chi tiết truy xuất, số liệu sử dụng, audit — nếu không ghi từ đầu thì dữ liệu quá khứ mất vĩnh viễn; không chứng minh được trợ lý đang tốt lên, không báo giá được.
- *Trạng thái:* D56, D58, D59 — ghi từ bản thử, giao diện xem làm sau.

**P73. Dùng LLM chấm điểm trên dữ liệu thật của khách** — [Nội bộ]
- *Vấn đề:* model local nhỏ chấm không đáng tin; model cloud chấm thì vi phạm D17.
- *Trạng thái:* D56 — dữ liệu thật chấm bằng chỉ số không cần LLM.

**P74. Cache câu trả lời làm lộ tài liệu giữa người dùng** — [Nội bộ]
- *Vấn đề:* hai người hỏi cùng câu nhưng có quyền khác nhau (D8); cache trả cho người thứ hai câu trả lời dựa trên tài liệu họ không được xem.
- *Trạng thái:* D58 — không cache câu trả lời theo nghĩa trong MVP.

**P75. Lỗi "im lặng" của tiếng Việt** — [Đối ngoại được, khi đã triển khai]
- *Vấn đề:* hai cách mã hóa dấu (NFC/NFD) và hai kiểu đặt dấu thanh ("hoà"/"hòa") khiến cùng một từ bị coi là hai từ; gõ không dấu không khớp; tìm kiếm thỉnh thoảng trượt mà không ai biết vì sao.
- *Trạng thái:* D60 — chuẩn hóa và chỉ mục bỏ dấu từ ngày đầu; test nạp cùng tài liệu ở NFC và NFD phải cho kết quả giống hệt.
- *Thông điệp đối ngoại gợi ý:* "Người dùng gõ có dấu hay không dấu, trợ lý đều hiểu."

---

## 4. Câu hỏi đã thảo luận

### Vòng 0 — Bức tranh tổng thể

| # | Câu hỏi | Đề xuất | Quyết định |
|---|---|---|---|
| 0.1 | Ai cài đặt và vận hành? Một hay nhiều khách hàng trên một bản cài? | Mỗi khách một bản cài | **Cả hai, ưu tiên bản cài tập trung** (D1) |
| 0.2 | Người dùng cuối chính là khách vãng lai hay người dùng đã xác thực? | Ưu tiên người dùng đã xác thực, ẩn danh bị giới hạn | Theo đề xuất (D2) |
| 0.3 | Điểm khác biệt là gì; tự xây hay xây trên nền mã nguồn mở? | Chốt định vị trước, làm spike so sánh | Chốt định vị (D3); spike còn mở |
| 0.4 | Hạ tầng tham chiếu và chất lượng tối thiểu của model local? | Cấu hình tham chiếu + nhãn yêu cầu theo tính năng + chế độ lai | Theo đề xuất; dev bắt đầu với máy hiện có (D4) |
| 0.5 | Xác nhận mô hình khái niệm và cắt phạm vi sơ bộ? | 5 điểm (Assistant/Channel, Skill+Tool, Answer Scripts, tách Connector, bỏ KG/Co-work khỏi MVP) | Theo đề xuất; Co-work = chọn file/folder (D5) |

### Vòng 1 — Module 1: Knowledge Base

| # | Câu hỏi | Quyết định |
|---|---|---|
| 1.1 | Nguyên tắc nền cho D1: một codebase multi-tenant, nhân sự vận hành không xem dữ liệu, sửa câu định vị | Theo đề xuất (D6) |
| 1.2 | Billing MVP làm đến đâu? | Đo mức sử dụng + chặn quota + hóa đơn thủ công (D7) |
| 1.3 | Phân quyền tri thức 3 mức theo Collection? | Đồng ý (D8) |
| 1.4 | MVP có OCR file scan không? | Chuyển sang giai đoạn sau (D9) |
| 1.5 | Excel chỉ tra cứu, không tính toán? | Đồng ý (D10) |

### Phạm vi MVP của Knowledge Base (đề xuất, chưa có phản đối)

- Upload PDF có lớp text, DOCX, XLSX/CSV, MD, TXT, HTML; DOC/XLS cũ qua chuyển đổi kèm cảnh báo chất lượng; có trạng thái xử lý từng tài liệu.
- Cấu trúc Collection → Folder; phân quyền 3 mức theo Collection.
- Kết hợp tìm theo từ khóa và theo ngữ nghĩa, có bước xếp hạng lại, tìm chéo Việt–Anh.
- Trích dẫn nguồn; chế độ chặt mặc định; ghi lại câu hỏi chưa trả lời được.
- Thay thế và xóa tài liệu sạch sẽ.
- Cách ly tenant; quota dung lượng và số trang theo Organization.
- Ô "hỏi thử" trong màn hình Collection.

### Vòng 1 — Module 2: Chatbot Widget

| # | Câu hỏi | Quyết định |
|---|---|---|
| 2.1 | Định danh bằng token do backend website chủ ký, khóa riêng theo Channel, chưa làm OIDC? | Theo đề xuất (D11) |
| 2.2 | Nhúng bằng iframe, Module 3 chỉ tùy biến bằng cấu hình? | Đồng ý (D12) |
| 2.3 | Chính sách lịch sử hội thoại (đăng nhập / ẩn danh / 90 ngày / quyền xem riêng)? | Đồng ý (D13) |
| 2.4 | Chuyển sang người thật ở mức tối giản, không xây hộp thư trực tiếp? | Đồng ý (D14) |
| 2.5 | Bốn biện pháp chống lạm dụng chế độ ẩn danh? | Theo đề xuất (D15) |

### Phạm vi MVP của Chatbot Widget (đề xuất, chưa có phản đối)

- Snippet tạo iframe; hai chế độ hiển thị: bong bóng nổi và nhúng vào trong trang.
- Chế độ đăng nhập dùng token ký theo Channel, có hàm làm mới token, hỗ trợ hai khóa song song khi đổi khóa. Chế độ ẩn danh có giới hạn.
- Danh sách domain được phép, giới hạn tần suất, trần chi phí theo ngày cho từng Channel.
- Câu trả lời hiện dần, có trạng thái từng bước và nút dừng; lọc HTML, chặn ảnh từ domain ngoài.
- Trích dẫn nguồn, đánh giá 👍/👎, lời chào, câu hỏi gợi ý.
- Lịch sử hội thoại với thời hạn lưu và quyền xem tách riêng.
- Chuyển tiếp tối giản qua email/webhook.
- Giao diện widget song ngữ Anh–Việt, dùng tốt trên điện thoại.
- Trang kiểm tra tích hợp và tài liệu tích hợp kèm ví dụ ký token.
- Widget xây trên chính API công khai sẽ mở cho khách sau này.

### Vòng 1 — Module 3 + 4: Appearance và AI Model Settings

| # | Câu hỏi | Quyết định |
|---|---|---|
| 3-4.1 | Model cloud chỉ BYOK; cloud tắt mặc định; cờ "Chỉ model local" theo Collection? | Đồng ý (D17) |
| 3-4.2 | Ghim phiên bản model, báo trước 30 ngày, không bao giờ tự đổi model? | Đồng ý (D18) |
| 3-4.3 | Instructions dạng biểu mẫu, ba tầng? | Đồng ý (D19) |
| 3-4.4 | Draft → Publish cho cấu hình Assistant; giao diện và tài liệu áp dụng ngay? | Đồng ý (D20) |
| 3-4.5 | Appearance ghi đè từng thuộc tính; branding trang quản trị để sau? | Đồng ý (D16) |

### Phạm vi MVP của Appearance và AI Model Settings (đề xuất, chưa có phản đối)

- Theme Organization và ghi đè từng thuộc tính ở Channel; kiểm tra tương phản; sáng/tối/tự động và hàm `setTheme`; xem trước trực tiếp; lời chào và câu gợi ý theo từng ngôn ngữ.
- Danh mục model của nền tảng có ghim phiên bản; BYOK cho OpenAI/Anthropic.
- Công tắc cloud cấp Organization (mặc định tắt); cờ "Chỉ model local" theo Collection.
- Mỗi Assistant chọn một model chat; embedding và reranker cấu hình ở cấp Organization hoặc nền tảng.
- Instructions dạng biểu mẫu, ba tầng; 3 preset; giới hạn độ dài câu trả lời; mẫu Instructions theo loại trợ lý.
- Draft → Publish, quay lại bản trước, Playground thử bản Draft.
- Thử lại một lần khi lỗi; không fallback sang cloud.
- Ghi model, phiên bản và preset vào từng tin nhắn.

### Vòng 1 — Module 6: Answer Scripts

| # | Câu hỏi | Quyết định |
|---|---|---|
| 6.1 | So khớp bằng embedding + reranker, 3 dải tin cậy? | Đồng ý (D22) |
| 6.2 | Ba loại kịch bản MVP; luồng nhiều bước sang Skills? | Đồng ý (D23) |
| 6.3 | Nội dung kịch bản có hiệu lực ngay; bản chụp Publish chỉ giữ danh sách bộ kịch bản? | Đồng ý (D24) |
| 6.4 | Nguyên văn mặc định; kịch bản thắng KB; thiếu ngôn ngữ thì hạ dải? | Đồng ý (D25) |
| 6.5 | Jev: key nền tảng + 7 điều kiện an toàn? | Theo đề xuất (D21) |

### Phạm vi MVP của Answer Scripts (đề xuất, chưa có phản đối)

- Ba loại kịch bản; bộ kịch bản gắn vào Assistant, phân quyền giống Collection.
- So khớp embedding + reranker, 3 dải tin cậy; Jev là nhà cung cấp tùy chọn theo D21.
- Nguyên văn / diễn đạt lại; xử lý thiếu ngôn ngữ.
- Trạng thái và ngày hết hạn từng kịch bản.
- Import FAQ từ Excel/CSV; tạo kịch bản từ câu hỏi chưa trả lời được; nút "thử khớp".

### Vòng 1 — Mở rộng Module 6: Pipeline xử lý câu hỏi

| # | Câu hỏi | Quyết định |
|---|---|---|
| P.1 | Pipeline 5 bước, Jev chỉ ở Script Matcher? | Đồng ý (D26) |
| P.2 | Classifier 7 loại, local, đọc 2 lượt, mặc định `thong_tin`? | Đồng ý (D27) |
| P.3 | Orchestrator kiểu lai? | Đồng ý (D28) |
| P.4 | Tối thiểu hóa dữ liệu gửi Jev? | Đồng ý (D29) |
| P.5 | Phạm vi spike: Script Matcher + Classifier? | Đồng ý (D30) |

```
Câu hỏi
  ▼
[1] GATE ─ luật, local: tần suất · chuẩn hóa · ngôn ngữ · che dữ liệu cá nhân · guardrail
  ▼
[2] CLASSIFIER ─ local, 2 lượt gần nhất
  ├─ chao_hoi / chuyen_nguoi / ngoai_pham_vi ─► mẫu / D14 / từ chối
  ├─ tiep_noi ─► bỏ qua [3], vào [4]
  ▼
[3] SCRIPT MATCHER ─ embedding lọc ứng viên ─► Jev (nếu bật) / reranker local
  ├─ dải cao ─► trả kịch bản ─► [5]
  ├─ dải trung bình ─► kịch bản làm ngữ cảnh ưu tiên cho [4]
  ▼  dải thấp / không có ứng viên
[4] ORCHESTRATOR ─ KB · Tool · Skill · LLM soạn câu trả lời (có ngân sách)
  ▼
[5] RESPONSE GUARD ─ trích dẫn · lọc hiển thị · ngôn ngữ · trace · không có thông tin → ghi lại
```

### Vòng 1 — Module 7 + 9: Skills/Tools và Data Connectors

| # | Câu hỏi | Quyết định |
|---|---|---|
| 7-9.1 | Lát mỏng trong MVP (HTTP Tool chỉ đọc + Skill kiểu cố định)? | Đồng ý (D31) |
| 7-9.2 | Tham số danh tính chỉ lấy từ token đã ký? | Đồng ý (D32) |
| 7-9.3 | Kết nối giai đoạn đầu: API HTTPS hoặc bản tự host; connector agent để sau? | Đồng ý (D33) |
| 7-9.4 | Ưu tiên API; không text-to-SQL; Tool ghi để sau và bắt buộc xác nhận? | Đồng ý (D34) |
| 7-9.5 | Skill bán cấu trúc, MVP chỉ kiểu cố định; MCP chỉ từ xa qua HTTP? | Đồng ý (D35) |

### Phạm vi MVP của Skills/Connectors (lát mỏng, đề xuất chưa có phản đối)

- Connector kiểu HTTP API: URL gốc, xác thực (API key hoặc chuyển tiếp token), secret mã hóa, danh sách domain được phép.
- Tool HTTP chỉ đọc: khai báo thủ công hoặc import OpenAPI; tham số gắn cứng từ token; timeout, giới hạn kết quả, tạm ngắt khi lỗi liên tục.
- Skill kiểu cố định, đi theo Draft → Publish.
- Orchestrator chọn Skill theo mô tả; không chọn được thì rơi về `thong_tin`.
- Playground chạy với token người dùng thử; trace lời gọi Tool đã che dữ liệu cá nhân.
- **Giai đoạn sau:** Skill kiểu linh hoạt, Tool ghi kèm xác nhận, DB qua truy vấn dựng sẵn, MCP từ xa, connector agent, mẫu Skill theo ngành, Tool tính toán an toàn.
- **Không khuyến nghị:** text-to-SQL cho người dùng cuối; MCP chạy cục bộ trên bản tập trung.

### Vòng 1 — Module 10: Memory, Schedule, MCP

| # | Câu hỏi | Quyết định |
|---|---|---|
| 10.1 | Memory không có trong MVP? | Đồng ý (D36) |
| 10.2 | Nguyên tắc Memory khi làm ở giai đoạn sau? | Đồng ý (D37) |
| 10.3 | Không bao giờ tự học chung từ hội thoại? | Đồng ý (D38) |
| 10.4 | Schedule thành thuộc tính thời gian; không làm tác vụ agent định kỳ? | Đồng ý (D39) |
| 10.5 | Bổ sung MCP: tự tắt khi tool thay đổi, xác thực, theo quy tắc Connector? | Đồng ý (D40) |

### Vòng 1 — Module 5 + 8: Co-work và Knowledge Graph

| # | Câu hỏi | Quyết định |
|---|---|---|
| 5-8.1 | KG không vào MVP và giai đoạn 2; chỉ xét lại khi có bằng chứng? | Đồng ý (D41) |
| 5-8.2 | Nếu làm sau: chỉ mục đồ thị nội bộ, không trình biên tập; bỏ ontology dựng tay, hiển thị trực quan? | Đồng ý (D42) |
| 5-8.3 | Từ điển thuật ngữ theo Workspace trong MVP? | Đồng ý (D43) |
| 5-8.4 | Metadata, tóm tắt phân cấp, mô tả Collection để sau; gắn nhãn nguyên nhân câu hỏi chưa trả lời được? | Đồng ý (D44) |
| 5-8.5 | Khép Co-work, bỏ hẳn thuật ngữ? | Đồng ý (D45) |

**Vòng 1 kết thúc tại đây.**

### Vòng 2 — Chủ đề 1: Multi-tenancy, RBAC và audit

| # | Câu hỏi | Quyết định |
|---|---|---|
| 2-1.1 | Cách ly hai lớp, khóa mã hóa theo Organization, bộ test cách ly? | Đồng ý (D46) |
| 2-1.2 | Đặt server trung tâm tại Việt Nam? | **Hoãn** — tùy khách; chốt trước khách trả tiền đầu tiên (D47) |
| 2-1.3 | RBAC ba tầng, vai trò cố định, tách ba quyền nhạy cảm? | Đồng ý (D48) |
| 2-1.4 | Bắt buộc 2FA cho vai trò nhạy cảm; SSO để sau? | Đồng ý (D49) |
| 2-1.5 | Audit log và vòng đời tenant trong MVP? | Đồng ý (D50) |

### Vòng 2 — Chủ đề 2: Bảo mật và quyền riêng tư

| # | Câu hỏi | Quyết định |
|---|---|---|
| 2-2.1 | Prompt injection theo nguyên tắc giới hạn thiệt hại; 3 lớp bắt buộc từ ngày đầu? | Đồng ý (D51) |
| 2-2.2 | Hội thoại lưu nguyên văn và mã hóa; log luôn che; xóa theo người dùng trong MVP? | Đồng ý (D52) |
| 2-2.3 | Cloud BYOK không che, có cảnh báo; Jev luôn che? | Đồng ý (D53) |
| 2-2.4 | Hạng mục pháp lý gom vào mốc trước khách trả tiền đầu tiên; link quyền riêng tư trong widget ở MVP? | **Chưa cần, bổ sung sau** (D54) |
| 2-2.5 | Công tắc khẩn cấp ở 5 phạm vi? | Đồng ý (D55) |

### Vòng 2 — Chủ đề 3–6: Chất lượng AI, hiệu năng, observability, tiếng Việt

| # | Câu hỏi | Quyết định |
|---|---|---|
| 2-3.1 | Bộ đo ba tầng; dữ liệu thật chấm bằng chỉ số không cần LLM; kiểm tra trích dẫn hợp lệ? | Đồng ý (D56) |
| 2-3.2 | Mục tiêu độ trễ, báo bận khi quá tải, ngân sách ngữ cảnh? | Đồng ý (D57) |
| 2-3.3 | Không cache câu trả lời; đo mức sử dụng từ bản thử? | Đồng ý (D58) |
| 2-3.4 | Trace có dấu phiên bản từ bản thử; analytics đầy đủ ở MVP? | Đồng ý (D59) |
| 2-3.5 | Chuẩn hóa Unicode, chỉ mục bỏ dấu từ ngày đầu; ô "Cách xưng hô"? | Đồng ý (D60) |

**Vòng 2 kết thúc tại đây.** Tổng hợp (Vòng 4): [tong-hop.md](tong-hop.md).

---

## 5. Bảng thuật ngữ thống nhất

| Thuật ngữ | Định nghĩa | Thay cho | Nhãn |
|---|---|---|---|
| Platform Operator | Nhân sự vận hành của nhà cung cấp: quản lý tenant, quota, billing, hạ tầng model | (mới) | MVP |
| Organization | Một khách hàng (tenant); giữ cấu hình chung | "Toàn hệ thống" | MVP |
| Workspace | Ranh giới cách ly dữ liệu và phân quyền trong một Organization | Workspace, Project | MVP |
| Assistant | "Bộ não" cấu hình được: model, instructions, tri thức, scripts, skills | Chatbot, Agent | MVP |
| Channel | Điểm triển khai của Assistant; widget là loại đầu tiên | Chatbot widget | MVP |
| Session variables | Thông tin website chủ truyền vào phiên chat; không ký nên không dùng để phân quyền | "Thêm context" (nghĩa b) | MVP |
| Identity token | Token ngắn hạn do backend website chủ ký, chứa user ID, tên, nhóm | (mới) | MVP |
| Instructions | Chỉ dẫn luôn áp dụng cho một Assistant | Instructions, "Thêm context" (nghĩa a) | MVP |
| Knowledge Collection / Folder / Document | Tài liệu đã đánh chỉ mục; Collection mang quyền truy cập | Knowledge Base | MVP |
| Knowledge Scope | Phạm vi tri thức được chọn (collection/folder) cho Assistant, sau này cho từng hội thoại | Co-work, Project | MVP (mức Assistant) |
| Answer Script | Ý định → phản hồi cố định | User Manual | MVP (dạng đơn giản) |
| Tool | Một hành động đơn lẻ (API, truy vấn dựng sẵn, tool từ MCP) | MCP | Giai đoạn sau |
| Data Connector | Kết nối chỉ đọc tới app có sẵn, cung cấp Tool | Kết nối dữ liệu app | Giai đoạn sau (ưu tiên cao) |
| Skill | Quy trình dùng lại được, kết hợp Tool và tri thức | Skills, Business Logic, Agents | Giai đoạn sau (ưu tiên cao) |
| Memory | Ghi nhớ về từng người dùng, phạm vi (người dùng × Assistant), chỉ các loại khai báo sẵn | Memory | Giai đoạn sau, tắt mặc định |
| Context | Khái niệm lúc chạy, không phải đối tượng cấu hình | Context | — |
| Knowledge Graph | Nếu có: chỉ mục đồ thị nội bộ cho bước truy xuất, không có giao diện riêng | Knowledge Graph | Không vào MVP và giai đoạn 2 (D41) |
| Glossary (Từ điển thuật ngữ) | Viết tắt, đồng nghĩa, tên cũ/mới, song ngữ theo Workspace | (mới) | MVP (D43) |
| Schedule | Không là đối tượng riêng — thuộc tính thời gian của kịch bản, nguồn đồng bộ, báo cáo | Schedule | MVP: hẹn giờ kịch bản |

---

## 6. Câu hỏi còn mở

| # | Câu hỏi | Xử lý ở |
|---|---|---|
| O1 | ~~Kết nối từ bản cài tập trung tới app nằm trong mạng nội bộ của khách (P8)~~ — đã xử lý ở D33 cho giai đoạn đầu; connector agent còn mở cho giai đoạn sau | Module Data Connector |
| O2 | Số phiên chat đồng thời để định cỡ hạ tầng production (P5) | Trước khi triển khai production |
| O3 | ~~Tự xây hay xây trên nền có sẵn (P1, P2)~~ — đã chốt ở D64; còn bước kiểm tra thư viện và giấy phép 1–2 ngày | Trước khi chọn tech stack |
| O4 | Ngành mục tiêu cho giai đoạn đầu (P3) — gắn với việc chọn khách thử nghiệm (D63) | Chọn khách thử nghiệm |
| O5 | ~~Ý nghĩa của "Schedule"~~ — đã xử lý ở D39 | Module Quản lý workspace |
| O6 | ~~Đánh giá Jev / Laya-MLX so với phương án đơn giản hơn (P12)~~ — đã xử lý ở D21, D29, D30 | Module Answer Scripts |
| O7 | Vị trí đặt server trung tâm và tư vấn pháp lý (D47); các hạng mục pháp lý đã hoãn (D54) | Trước khách trả tiền đầu tiên |
| O8 | Khách thử nghiệm đầu tiên là ai; app của họ có API gọi tới được không (D33) | Mốc M4 của bản thử |
| O9 | Quy mô đội phát triển và tech stack | Giai đoạn thiết kế |
| O10 | Nâng cấp máy dev (RAM 64 GB hoặc GPU rời) hay thuê GPU theo giờ | Khi bắt đầu đo chất lượng |

---

## 7. Gợi ý câu hỏi – trả lời cho khách hàng

Chỉ dùng khi tính năng tương ứng đã được triển khai và kiểm chứng.

- **Dữ liệu của tôi có bị gửi cho OpenAI hay nhà cung cấp AI khác không?** — Không, trừ khi quản trị viên của bạn chủ động bật một nhà cung cấp bên ngoài. Mặc định trợ lý dùng model chạy trên hạ tầng do chúng tôi hoặc bạn kiểm soát. (D3, D4)
- **Tôi có thể tự host không?** — Có, theo hợp đồng; bản tự host dùng cùng một sản phẩm với bản vận hành tập trung. (D1, D6)
- **Nhân viên của nhà cung cấp có xem được dữ liệu của tôi không?** — Mặc định không. Khi cần hỗ trợ, bạn cấp quyền có thời hạn và mọi truy cập đều được ghi lại. (D6)
- **Khách hàng khác có thấy dữ liệu của tôi không?** — Không. Dữ liệu mỗi khách hàng được cách ly riêng. (P15)
- **Trợ lý có trả lời cho người không được phép xem tài liệu không?** — Không. Trợ lý chỉ đọc những tài liệu mà chính người hỏi được phép xem. (D8, P14)
- **AI có bịa câu trả lời không?** — Mặc định trợ lý chỉ trả lời từ tài liệu của bạn, luôn kèm nguồn trích dẫn, và nói rõ khi không tìm thấy thông tin. (P17)
- **Xóa tài liệu thì AI còn nhớ không?** — Không. Xóa là xóa khỏi toàn bộ hệ thống. (P18)
- **Hỏi tiếng Việt có tìm được tài liệu tiếng Anh không?** — Có. (P21)
- **Trợ lý có tính toán trên file Excel được không?** — Hiện tại trợ lý tra cứu được thông tin trong Excel; tính toán tổng hợp sẽ có qua kết nối dữ liệu ở phiên bản sau. (D10)
- **Tích hợp có phải sửa lại website không?** — Không. Chỉ cần dán một đoạn mã nhúng; muốn trợ lý biết người dùng là ai thì thêm một endpoint nhỏ ở backend để ký token. (D11, D12)
- **Widget có làm vỡ giao diện website của tôi không?** — Không. Widget chạy trong khung cách ly, không ảnh hưởng CSS hay mã của trang. (D12)
- **Lịch sử chat được lưu bao lâu, ai xem được?** — Mặc định 90 ngày, bạn chỉnh được. Chỉ những người được cấp quyền "xem hội thoại" mới đọc được. (D13)
- **Có chuyển cho nhân viên thật được không?** — Có: trợ lý chuyển bản ghi hội thoại vào email hoặc hệ thống CSKH bạn đang dùng. (D14)
- **Người lạ spam chatbot thì sao?** — Có giới hạn tần suất và trần chi phí theo ngày, nên chi phí không vượt mức bạn đặt. (D15)
- **Model AI có bị thay đổi mà tôi không biết không?** — Không. Mỗi trợ lý gắn với một phiên bản model cố định; mọi thay đổi đều được báo trước tối thiểu 30 ngày và bạn chủ động chuyển. (D18)
- **Tôi có thể dùng OpenAI/Anthropic không?** — Có, bằng API key của chính bạn, sau khi quản trị viên bật cho phép. Tài liệu bạn đánh dấu "chỉ model local" không bao giờ được gửi ra ngoài. (D17)
- **Sửa cấu hình sai thì sao?** — Mọi thay đổi được thử ở bản nháp trước khi áp dụng, và quay lại bản trước chỉ bằng một thao tác. (D20)
- **Trợ lý có làm việc được trên dữ liệu của app tôi không?** — Có: trợ lý tra cứu được dữ liệu qua API của app (ví dụ tình trạng đơn hàng), và chỉ thấy dữ liệu của chính người đang hỏi. (D31, D32)
- **Trợ lý có tự ý sửa dữ liệu của tôi không?** — Không. Hiện trợ lý chỉ đọc; khi có tính năng thao tác, mọi thay đổi đều phải được người dùng xác nhận. (D34)
- **App của tôi chỉ chạy trong mạng nội bộ thì sao?** — Bạn có thể triển khai bản tự host ngay trong mạng nội bộ. (D33)
- **Trợ lý có tự học từ người dùng không?** — Không. Mọi kiến thức mới đều do đội ngũ của bạn duyệt, nên không ai "dạy sai" được trợ lý. (D38)
