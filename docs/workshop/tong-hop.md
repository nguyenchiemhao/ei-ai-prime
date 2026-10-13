# ei-ai assistant — Tổng hợp workshop phân tích sản phẩm

- **Cập nhật:** 2026-10-13
- **Phạm vi:** kết quả Vòng 0, 1, 2 của workshop. Vòng 3 (chức năng bổ sung) để sau khi có bản thử.
- **Dùng để:** đầu vào cho giai đoạn thiết kế (kiến trúc, tech stack, mô hình dữ liệu).
- **Chi tiết từng quyết định và phản biện:** [phan-bien-va-quyet-dinh.md](phan-bien-va-quyet-dinh.md) (D1–D67, P1–P75). Mã `Dxx` trong tài liệu này trỏ tới file đó.
- **Kế hoạch spike Jev:** [jev-spike.md](jev-spike.md).

Mục 6 và mục 9 là đề xuất của tài liệu tổng hợp, đã được chủ dự án xác nhận (D61, D62).

---

## 1. Sản phẩm trong một trang

**Định vị (D3):**
> Trợ lý AI nhúng vào web app sẵn có của doanh nghiệp, biết người dùng đang đăng nhập là ai, đọc và thao tác được trên dữ liệu của chính app đó, hỗ trợ tốt tiếng Việt và tiếng Anh. Dữ liệu không được gửi cho nhà cung cấp AI bên thứ ba nào, trừ khi khách chủ động bật. Có thể triển khai riêng trên hạ tầng của khách.

**Triển khai (D1, D6):** hướng chính là một bản cài tập trung do bên mình vận hành cho nhiều khách (mỗi khách là một Organization). Hướng phụ là bản tự host theo hợp đồng. Một codebase duy nhất, luôn chạy multi-tenant.

**Người dùng cuối (D2):** ưu tiên người dùng đã đăng nhập trên web app của khách (danh tính do backend của khách ký). Chế độ ẩn danh có nhưng bị giới hạn.

**Chat trực tiếp trên console (D67):** ngoài widget nhúng, thành viên đã đăng nhập console của ei-ai có trang **Chat** để dùng Assistant như một web app — cùng pipeline, cùng phân quyền tri thức và Skill, qua một Channel nội bộ "Console chat" có sẵn trong mỗi Workspace.

**Khác biệt so với Dify / MaxKB / AnythingLLM** (P1):
1. Biết người dùng là ai một cách tin cậy, và phân quyền tri thức theo người hỏi (D8, D11).
2. Đọc dữ liệu sống của app qua Skill, với danh tính gắn cứng — LLM không thể bị lừa để xem dữ liệu người khác (D31, D32).
3. Pipeline có kiểm soát: kịch bản trả lời nguyên văn, phân loại câu hỏi, điều phối có ngân sách (D26–D28).
4. Cam kết dữ liệu thực thi bằng kỹ thuật: model local mặc định, cờ "chỉ model local", không fallback ra cloud, ghim phiên bản model (D17, D18).
5. Làm tốt tiếng Việt: chuẩn hóa Unicode, gõ không dấu, từ viết tắt, cách xưng hô (D43, D60).

---

## 2. Persona và vai trò

| Persona | Vai trò hệ thống (D48) |
|---|---|
| Nhân sự vận hành của bên mình | Platform Admin, Platform Support, Billing |
| Quản trị phía khách | Org Owner, Org Admin |
| Chủ workspace | Workspace Admin |
| Lập trình viên tích hợp của khách | Developer |
| Người dựng trợ lý | Builder |
| Chuyên gia nghiệp vụ | Knowledge Editor |
| Người xem chất lượng | Reviewer |
| Quản lý | Viewer |
| Nhân viên dùng trợ lý trên console | Member — chỉ thấy trang Chat; nhóm tri thức và External user ID do Org Admin gán (D67) |
| Người dùng cuối của widget (đã đăng nhập / ẩn danh) | Không thuộc RBAC — quyền đến từ token (D8, D11) |

Ba quyền nhạy cảm tách riêng: đọc hội thoại (Reviewer), quản lý secret/Connector (Developer), Publish (Builder).

---

## 3. Mô hình khái niệm

### 3.1 Phân cấp đối tượng

```
Platform (bản cài tập trung hoặc tự host)
└── Organization  (= một khách hàng; khóa mã hóa riêng)
    ├── Thành viên console + vai trò (kể cả Member) · nhóm tri thức · External user ID (D67)
    ├── Model providers (local / BYOK cloud) · công tắc cloud · công tắc Jev
    ├── Theme mặc định · chính sách Organization
    └── Workspace  (ranh giới dữ liệu & phân quyền)
        ├── Knowledge: Collection (Public / Authenticated / Restricted) → Folder → Document
        ├── Glossary (từ điển thuật ngữ)
        ├── Answer Scripts (theo bộ)
        ├── Connector → Tool (chỉ đọc)
        ├── Skill (kiểu cố định)
        └── Assistant  (Draft → Published, quay lại được)
            ├── Model (ghim phiên bản) · Instructions (3 tầng) · preset
            ├── Gắn: Collection/Folder · bộ kịch bản · Skill
            └── Channel (1..n) — Widget, hoặc Channel nội bộ "Console chat" có sẵn (D67)
                ├── Domain được phép · khóa ký token · chế độ ẩn danh
                ├── Giao diện ghi đè từng thuộc tính
                └── Conversation → Message (+ trace, phản hồi)
```

### 3.2 Pipeline xử lý câu hỏi (D26–D29)

```
Câu hỏi
  ▼
[1] GATE ─ luật, local: tần suất · chuẩn hóa Unicode · ngôn ngữ · che dữ liệu cá nhân · guardrail
  ▼
[2] CLASSIFIER ─ local, 2 lượt gần nhất; không chắc → thong_tin
  ├─ chao_hoi / chuyen_nguoi / ngoai_pham_vi ─► mẫu / chuyển tiếp / từ chối
  ├─ tiep_noi ─► bỏ qua [3]
  ▼
[3] SCRIPT MATCHER ─ embedding lọc ứng viên ─► Jev (nếu bật, đã che) / reranker local
  ├─ dải cao ─► trả kịch bản nguyên văn ─► [5]
  ├─ dải trung bình ─► kịch bản làm ngữ cảnh ưu tiên cho [4]
  ▼
[4] ORCHESTRATOR ─ khung cố định theo loại câu hỏi
      thong_tin → RAG trên mọi Collection được gắn (đã lọc quyền)
      tac_vu / du_lieu → Skill kiểu cố định → Tool chỉ đọc (danh tính gắn từ token)
  ▼
[5] RESPONSE GUARD ─ trích dẫn hợp lệ · lọc hiển thị · canary · ngôn ngữ · trace có dấu phiên bản
```

### 3.3 Thuật ngữ chính thức

| Thuật ngữ | Định nghĩa |
|---|---|
| Organization | Một khách hàng (tenant) |
| Workspace | Ranh giới dữ liệu và phân quyền trong Organization |
| Assistant | "Bộ não" cấu hình được: model, instructions, tri thức, kịch bản, skill |
| Channel | Điểm triển khai của Assistant; widget là loại đầu tiên |
| Identity token | Token ngắn hạn do backend website chủ ký: user ID, tên, nhóm |
| Session variables | Thông tin website chủ truyền vào phiên, không ký, không dùng để phân quyền |
| Instructions | Chỉ dẫn luôn áp dụng; 3 tầng: guardrail nền tảng → chính sách Organization → Assistant |
| Collection / Folder / Document | Tài liệu đã đánh chỉ mục; Collection mang quyền truy cập |
| Knowledge Scope | Phạm vi tri thức (Collection/Folder) gắn cho Assistant |
| Glossary | Từ viết tắt, đồng nghĩa, tên cũ/mới, song ngữ |
| Answer Script | Ý định → phản hồi cố định (nguyên văn mặc định) |
| Decision Provider | Thành phần chọn nhãn kèm xác suất ở Script Matcher: reranker local hoặc Jev |
| Connector | Kết nối tới app của khách (HTTP API trong giai đoạn đầu) |
| Tool | Một hành động đơn lẻ, cung cấp bởi Connector hoặc MCP |
| Skill | Quy trình bán cấu trúc dùng Tool và tri thức; kiểu cố định / linh hoạt |
| Memory | (Giai đoạn sau) ghi nhớ về từng người dùng, phạm vi người dùng × Assistant |
| Context | Khái niệm lúc chạy, không phải đối tượng cấu hình |

Đã bỏ: Co-work, Project, User Manual, Business Logic (như module riêng), Schedule (như module riêng), Agent (như đối tượng riêng).

---

## 4. Quyết định đã chốt — theo nhóm

| Nhóm | Tóm tắt | Mã |
|---|---|---|
| Định vị, triển khai | Bản tập trung là chính, tự host là phụ; một codebase multi-tenant; nhân sự vận hành mặc định không xem dữ liệu khách | D1, D3, D6 |
| Người dùng cuối, widget | Ưu tiên đã đăng nhập; token do backend khách ký; iframe; lịch sử 90 ngày; chuyển người thật tối giản; chống lạm dụng ẩn danh | D2, D11–D15 |
| Knowledge Base | Phân quyền 3 mức theo Collection, lọc trước khi vào LLM; OCR để sau; Excel chỉ tra cứu; Glossary trong MVP; KG không vào MVP và giai đoạn 2 | D8–D10, D41–D45 |
| Giao diện | Ghi đè từng thuộc tính; áp dụng ngay khi lưu | D16 |
| Model | Local mặc định; cloud chỉ BYOK, tắt mặc định; cờ "chỉ model local"; ghim phiên bản; không fallback ra cloud; Instructions 3 tầng; Draft → Publish | D4, D17–D20 |
| Kịch bản, Jev | 3 loại kịch bản; nội dung có hiệu lực ngay; nguyên văn mặc định; Jev tùy chọn với key nền tảng, che dữ liệu, chỉ ở Script Matcher, luôn có đường local | D21–D25, D29, D30 |
| Pipeline | 5 bước; Classifier 7 loại, local; Orchestrator kiểu lai | D26–D28 |
| Skills, Connector | Lát mỏng trong MVP: HTTP Tool chỉ đọc + Skill cố định; danh tính gắn từ token; API HTTPS hoặc tự host; không text-to-SQL; MCP chỉ từ xa | D31–D35, D40 |
| Memory, Schedule | Không memory trong MVP; không tự học chung; Schedule là thuộc tính thời gian | D36–D39 |
| Multi-tenancy, RBAC, audit | Cách ly hai lớp + khóa theo Organization; RBAC ba tầng (thêm vai trò Member chỉ dùng Chat); 2FA; audit log | D46, D48–D50, D67 |
| Chat trên console | Trang Chat cho thành viên đã đăng nhập; Channel nội bộ có sẵn; nhóm và External user ID do Org Admin gán; Reviewer chỉ mở hội thoại có đánh giá | D67 |
| Bảo mật, quyền riêng tư | Giới hạn thiệt hại khi bị chèn lệnh; hội thoại nguyên văn mã hóa, log luôn che; công tắc khẩn cấp | D51–D53, D55 |
| Chất lượng, hiệu năng, observability | Bộ đo ba tầng; mục tiêu độ trễ; không cache câu trả lời; đo sử dụng và trace từ bản thử | D56–D59 |
| Tiếng Việt | Chuẩn hóa Unicode, chỉ mục bỏ dấu từ ngày đầu; cách xưng hô | D60 |
| **Đã hoãn** | Vị trí server và tư vấn pháp lý; các hạng mục pháp lý (DPA, bên xử lý phụ, thông báo vi phạm, pentest, link quyền riêng tư) | D47, D54 → O7 |

---

## 5. Nền móng phải có từ ngày đầu

Những thứ dưới đây **không thể thêm sau** mà không phải làm lại hoặc mất dữ liệu quá khứ. Chúng phải có **ngay trong bản thử**, dù giao diện quản lý có thể làm sau.

| # | Nền móng | Vì sao không thêm sau được | Mã |
|---|---|---|---|
| F1 | Mô hình dữ liệu multi-tenant: `org_id` mọi bảng + DB tự áp cách ly theo dòng | Thêm sau = rà lại toàn bộ dữ liệu và truy vấn | D46 |
| F2 | Chỉ mục vector tách theo Organization; khóa mã hóa theo Organization | Đổi sau = nạp lại toàn bộ, mã hóa lại toàn bộ | D46 |
| F3 | Tenant chỉ lấy từ thông tin xác thực; bộ test cách ly trong CI | Lỗi rò dữ liệu khó phát hiện khi đã chạy | D46 |
| F4 | Token danh tính do backend khách ký; tham số danh tính của Tool gắn từ token | Là nền của phân quyền tri thức và Skill | D11, D32 |
| F5 | Lọc quyền trước khi truy xuất | Thêm sau = mọi luồng truy xuất phải sửa | D8 |
| F6 | Giới hạn khả năng LLM + tách lệnh/dữ liệu + lọc đầu ra | Kiến trúc chống prompt injection | D51 |
| F7 | Assistant có Draft/Published; Channel trỏ tới bản Published | Thay đổi mô hình dữ liệu cốt lõi | D20 |
| F8 | Gọi model qua lớp tương thích OpenAI; ghim phiên bản model | Đổi model là đổi cấu hình, không sửa code | D4, D18 |
| F9 | Chuẩn hóa Unicode lúc nạp và ở Gate; chỉ mục bỏ dấu | Đổi sau = nạp lại toàn bộ tài liệu | D60 |
| F10 | Trace từng tin nhắn có dấu phiên bản và chi tiết truy xuất | Dữ liệu quá khứ không tính bù được | D56, D59 |
| F11 | Đo mức sử dụng chi tiết | Không tính bù được; cần để báo giá | D58 |
| F12 | Ghi sự kiện audit (giao diện xem để sau) | Không tính bù được | D50 |
| F13 | Log hệ thống che dữ liệu cá nhân ở tầng thư viện | Log đã lộ không thu hồi được | D52 |
| F14 | Mọi lời gọi ra ngoài qua proxy có danh sách domain được phép | Chống SSRF và rò dữ liệu qua Tool | D33 |
| F15 | Bộ đo nền tảng chạy được bằng một lệnh | Không có thì không biết thay đổi nào làm tệ đi | D4, D56 |

---

## 6. Phạm vi bản thử ✅ Đã xác nhận (D61)

**Mục tiêu bản thử:** chứng minh được định vị D3 với một doanh nghiệp thật hoặc giả định — trợ lý trả lời đúng từ tài liệu, trả kịch bản nguyên văn, và tra cứu được dữ liệu của app theo đúng người hỏi — trên model local.

**Điều kiện dữ liệu (P65):** chỉ dữ liệu giả, hoặc dữ liệu của khách thử nghiệm có đồng ý bằng văn bản, hoặc triển khai tự host tại khách.

| Khu vực | Có trong bản thử | Để MVP |
|---|---|---|
| Nền móng | **Toàn bộ F1–F15** | — |
| Organization | Platform Operator tạo thủ công 1–2 Organization | Tạm ngưng, xóa có quy trình, giao diện quota |
| Đăng nhập, vai trò | Email + mật khẩu; vai trò đủ như D48 ở tầng kiểm tra quyền, giao diện gán vai trò tối giản | 2FA bắt buộc (D49) |
| Knowledge Base | Upload PDF có text, DOCX, XLSX/CSV, MD, TXT; Collection → Folder; phân quyền 3 mức; tìm từ khóa + ngữ nghĩa + reranker; trích dẫn; chế độ chặt; thay/xóa tài liệu; ô hỏi thử; Glossary | DOC/XLS cũ, HTML, quét tài liệu khi nạp, cảnh báo dữ liệu cá nhân trong Collection Public |
| Widget | Iframe, bong bóng nổi; token ký + ẩn danh có giới hạn; domain được phép; giới hạn tần suất; trả lời dạng stream; trích dẫn; 👍/👎 kèm lý do; lời chào, câu gợi ý; song ngữ; lọc HTML, chặn ảnh ngoài | Chế độ nhúng trong trang, lịch sử trên mọi thiết bị, trần chi phí theo Channel, chuyển người thật, trang kiểm tra tích hợp |
| Giao diện | Màu chủ đạo, avatar, tên, vị trí, sáng/tối — ở cấp Channel | Kế thừa từ Theme Organization, kiểm tra tương phản, `setTheme` |
| Model | Model local qua lớp tương thích OpenAI; BYOK cloud có công tắc; ghim phiên bản; Instructions dạng biểu mẫu (có ô xưng hô) + 3 tầng; preset | Mẫu Instructions theo loại trợ lý |
| Assistant | Draft → Publish | Quay lại bản trước, Playground đầy đủ |
| Pipeline | Đủ 5 bước: Gate, Classifier (luật + embedding), Script Matcher (reranker local; **Jev nếu đã có key**), Orchestrator, Response Guard (trích dẫn hợp lệ, canary) | Sàng lọc đầu vào ghi log |
| Kịch bản | Hỏi–đáp cố định + biến; nguyên văn/diễn đạt lại; 3 dải; import CSV; trạng thái và ngày bắt đầu/kết thúc; nút thử khớp | Tạo kịch bản từ câu chưa trả lời được, thống kê từng kịch bản |
| Skill, Connector | **Một Connector HTTP** + Tool chỉ đọc khai báo thủ công + **một Skill kiểu cố định** (ví dụ tra cứu đơn hàng); danh tính gắn từ token; proxy đầu ra; Playground với token thử | Import OpenAPI, nhiều Skill, trace Tool trong giao diện |
| Chat trên console | Trang Chat (sau M2): hội thoại có trích dẫn, bảng Sources, thẻ kết quả Skill, lịch sử 90 ngày có tìm kiếm, vai trò Member (D67) | Chia sẻ hội thoại, tải file trong chat, giao diện mobile, SSO |
| Vận hành | Công tắc: tắt Channel, tắt Tool, tắt cloud/Jev | Tắt Jev toàn nền tảng qua giao diện |
| Quan sát | Trace, số liệu sử dụng, dashboard cơ bản, danh sách câu chưa trả lời được | Cảnh báo, analytics đầy đủ, giao diện audit |

---

## 7. Phạm vi MVP

**MVP = bản thử + các mục cột "Để MVP" ở mục 6 +** các mục sau:

- 2FA bắt buộc cho vai trò nhạy cảm (D49); giao diện audit log (D50); vòng đời tenant (D50).
- Xóa mọi dữ liệu của một người dùng theo yêu cầu (D52).
- Quota theo Organization có chặn, trần chi phí theo ngày cho Channel (D7, D15).
- Bộ test tấn công song ngữ chạy trước khi khách thật dùng (D51).
- Bộ đo theo từng khách lúc onboarding (D56).
- Cảnh báo vận hành và analytics cho khách (D59).
- Spike Jev hoàn tất và quyết định giữ/bỏ theo tiêu chí (D30).

**Trước khách trả tiền đầu tiên (O7):** vị trí server, tư vấn pháp lý, DPA, danh sách bên xử lý phụ, quy trình thông báo vi phạm, pentest, link chính sách quyền riêng tư trong widget (D47, D54).

---

## 8. Giai đoạn sau và không khuyến nghị

### Giai đoạn sau (xếp theo ưu tiên đề xuất)

1. Connector agent cho app trong mạng nội bộ khi dùng bản tập trung (D33).
2. Skill kiểu linh hoạt; Tool ghi kèm xác nhận trong widget (D34, D35).
3. Nhập từ URL/sitemap website; đồng bộ Drive/SharePoint; đồng bộ định kỳ (Module 1, D39).
4. Báo cáo định kỳ cho chủ workspace (D39).
5. Metadata tài liệu và bộ lọc; tóm tắt phân cấp; mô tả Collection (D44).
6. Chạy bộ câu hỏi mẫu trên Draft so với Published trước khi Publish (Module 4).
7. OCR tiếng Việt (D9).
8. SSO, API key, API công khai (D49).
9. Memory theo D37.
10. MCP từ xa; ei-ai làm MCP server (D35, D40).
11. Branding trang quản trị, domain riêng, ẩn "Powered by" (D16).
12. Chọn file/folder theo từng hội thoại; AI gợi ý tổ chức KB (D45).
13. Kết nối DB qua truy vấn dựng sẵn (D34).
14. Laya bản gốc cho Classifier (D27).

### Không khuyến nghị

- Text-to-SQL cho người dùng cuối (D34).
- MCP chạy tiến trình cục bộ trên bản tập trung (D35).
- Ghi nhớ chung tự học từ hội thoại (D38).
- Tác vụ agent chạy định kỳ; chủ động nhắn người dùng (D39).
- Ontology dựng tay; hiển thị Knowledge Graph trực quan (D42).
- Fallback từ model local sang cloud (D18).
- Cache câu trả lời theo nghĩa (D58).
- Tự xây hộp thư chat trực tiếp (D14).
- Laya-MLX (chỉ chạy Apple Silicon).

---

## 9. Thứ tự xây dựng bản thử ✅ Đã xác nhận (D62)

Chỉ nêu thứ tự và phụ thuộc, chưa ước lượng thời gian (cần biết quy mô đội và tech stack).

| Mốc | Nội dung | Phụ thuộc | Kết quả kiểm chứng được |
|---|---|---|---|
| **M0 — Nền móng** | F1–F3, F7, F8, F10–F13; chuẩn hóa Unicode (F9); đăng nhập + vai trò; bộ đo nền tảng (F15) | — | Test cách ly tenant xanh; gọi được model local qua lớp OpenAI; bộ đo chạy bằng một lệnh |
| **M1 — Knowledge Base + RAG** | Upload, chia đoạn, chỉ mục từ khóa (có bản bỏ dấu) + ngữ nghĩa, reranker, lọc quyền (F5), trích dẫn, chế độ chặt, ô hỏi thử, Glossary | M0 | Hỏi trong ô hỏi thử ra câu trả lời có trích dẫn; test NFC/NFD giống hệt |
| **M2 — Widget** | Iframe, token ký (F4), ẩn danh có giới hạn, stream, phản hồi, lọc đầu ra (F6) | M1 | Nhúng vào một trang mẫu; người dùng nhóm A không thấy tài liệu Restricted của nhóm B |
| **M3 — Pipeline + Kịch bản** | Gate, Classifier, Script Matcher (local), quản lý kịch bản, Response Guard đầy đủ | M1, M2 | Bộ test spike: đo được khớp nhầm ở dải cao và ma trận Classifier |
| **M3b — Jev** | Decision Provider Jev, che dữ liệu, rơi về local | M3, có key | Chỉ số S3 trong [jev-spike.md](jev-spike.md) |
| **M4 — Skill lát mỏng** | Connector HTTP, Tool chỉ đọc, Skill cố định, proxy đầu ra (F14), Playground với token thử | M2, M3 | Người dùng A gõ ID của B vẫn không thấy dữ liệu của B |
| **M5 — Hoàn thiện bản thử** | Assistant Draft → Publish, biểu mẫu Instructions, giao diện Channel, công tắc khẩn cấp, dashboard, danh sách câu chưa trả lời được | M0–M4 | Demo trọn vẹn với doanh nghiệp giả định hoặc khách thử nghiệm |

**Song song với M0–M3:** spike Jev phần local (S1, S2, C1) — dùng chung bộ test với M3.

---

## 10. Câu hỏi còn mở

| # | Câu hỏi | Cần trả lời trước |
|---|---|---|
| O2 | Số phiên chat đồng thời để định cỡ hạ tầng production | Triển khai production |
| O3 | ~~Tự xây lõi hay xây trên nền mã nguồn mở có sẵn~~ — đã chốt tự xây lõi, dùng lại thư viện (D64); còn kiểm tra thư viện và giấy phép 1–2 ngày | Trước khi chọn tech stack |
| O4 | Ngành mục tiêu giai đoạn đầu | Chọn khách thử nghiệm |
| O7 | Vị trí server; tư vấn pháp lý; các hạng mục pháp lý đã hoãn | Khách trả tiền đầu tiên |
| O8 | Khách thử nghiệm đầu tiên là ai; app của họ có API gọi tới được không (D33) | Mốc M4 |
| O9 | Quy mô đội phát triển và tech stack | Giai đoạn thiết kế |
| O10 | Nâng cấp máy dev (RAM 64 GB, hoặc GPU rời) hay thuê GPU theo giờ | Mốc M1 (khi bắt đầu đo chất lượng) |

---

## 11. Rủi ro lớn nhất cần xử lý trước khi thiết kế

| # | Rủi ro | Vì sao lớn | Xử lý |
|---|---|---|---|
| R1 | **Chưa chốt tự xây hay dựa trên nền có sẵn (O3)** | Quyết định này định hình toàn bộ kiến trúc và công sức | Chốt ngay đầu giai đoạn thiết kế. Với 60 quyết định đã có (pipeline riêng, cách ly hai lớp, danh tính gắn cứng), khả năng cao là **tự xây lõi, dùng lại thư viện** (đọc file, chỉ mục, phục vụ model) thay vì nền tảng — nhưng cần một kiểm tra ngắn về giấy phép và thành phần dùng lại được |
| R2 | **Chất lượng model local với tiếng Việt và với Skill chưa được đo** | Cả định vị "local-first" dựa vào điều này | Bộ đo nền tảng ở M0; đo trên GPU thuê theo giờ sớm, không đợi tới M5 |
| R3 | **Phạm vi bản thử vẫn lớn với đội nhỏ** | 6 mốc, nhiều nền móng | Giữ kỷ luật: chỉ những gì trong mục 6; mọi yêu cầu mới đi vào Vòng 3 sau bản thử |
| R4 | **Lỗi ở cách ly tenant hoặc gắn danh tính** | Một lỗi = sự cố chấm dứt sản phẩm | Test cách ly và test lừa danh tính là điều kiện qua mốc M0, M2, M4 |
| R5 | **Khách thử nghiệm không có API gọi tới được** | Không demo được vế "dữ liệu sống" của định vị | Chọn khách thử nghiệm theo tiêu chí này (O8), hoặc dùng app giả định |
| R6 | **Phụ thuộc Jev early access** | Key có thể chưa được cấp | Jev là M3b tách riêng; bản thử chạy đủ không cần Jev |
| R7 | **Pháp lý bị hoãn** | Ký khách trước khi sẵn sàng | O7 là điều kiện cứng trước khách trả tiền |
| R8 | **Máy dev yếu làm sai lệch cảm nhận về tốc độ và chất lượng** | Team kết luận sai về khả thi | Không kết luận chất lượng trên máy dev (D4); thuê GPU khi đo |

---

## 12. Việc làm ngay

1. Đăng ký early access Jev (key cấp theo đợt).
2. Bắt đầu viết bộ test của spike (40 kịch bản, 400 câu) — dùng chung cho M3 và bộ đo nền tảng.
3. Chốt O3 (tự xây hay dựa trên nền có sẵn) và O9 (đội, tech stack) — mở đầu giai đoạn thiết kế.
4. Chọn doanh nghiệp giả định hoặc khách thử nghiệm (O4, O8).
5. Quyết định nâng cấp máy dev hay thuê GPU (O10).
6. Chạy benchmark model trên máy dev khi cần (đã hoãn theo yêu cầu).
