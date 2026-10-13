# ei-ai assistant — Quyết định thiết kế giao diện

- **Cập nhật:** 2026-10-12
- **Giai đoạn:** thiết kế giao diện cho bản thử (D61, D65 trong [phan-bien-va-quyet-dinh.md](../workshop/phan-bien-va-quyet-dinh.md))
- **Mục đích:** dùng giao diện để kiểm tra, hình dung ý tưởng và xác định hướng làm, trước khi chọn tech stack và kiến trúc.
- **Đầu vào:** [tong-hop.md](../workshop/tong-hop.md) — phạm vi bản thử (mục 6), nền móng F1–F15 (mục 5), thuật ngữ chính thức (mục 3.3).

---

## 1. Quyết định đã chốt

| # | Quyết định | Ghi chú |
|---|---|---|
| UI1 | **Vẽ tất cả các màn hình cần thiết** cho bản thử, không chia đợt | Danh sách ở mục 4 |
| UI2 | **Mức độ chi tiết: mid-fidelity** — bố cục thật, nội dung thật, phong cách trung tính. Không làm wireframe xám, chưa làm giao diện hoàn thiện theo thương hiệu | |
| UI3 | **Trang quản trị bằng tiếng Anh.** Nội dung mẫu (tài liệu, kịch bản, hội thoại) có cả tiếng Việt và tiếng Anh; widget thể hiện cả hai ngôn ngữ | Khớp ưu tiên "tiếng Anh trước" ở bối cảnh ban đầu |
| UI4 | **Công cụ: Design artifact trên claude.ai** (canvas nhiều artboard, riêng tư, comment được) | Chưa có design system trong tài khoản |
| UI5 | **Doanh nghiệp giả định: công ty công nghệ làm outsource, quản lý đội software engineer** | Thay cho "cửa hàng điện máy" đề xuất trước đó; cập nhật D63 |
| UI6 | **Phong cách trung tính**; tạo design system tối giản khi hướng giao diện đã rõ | Chưa có màu, logo, font của ei-ai |

---

## 2. Nguyên tắc thiết kế

1. **Chỉ vẽ trong phạm vi bản thử (D61).** Màn hình hoặc thành phần ngoài phạm vi, nếu cần để hình dung, phải gắn nhãn **"Later"** rõ ràng. Mục đích: tránh phình phạm vi (rủi ro R3).
2. **Làm lộ ra các quyết định "vô hình".** Giao diện phải cho người dùng thấy:
   - Nhãn quyền Collection: Public / Authenticated / Restricted (D8).
   - Trace 5 bước của pipeline cho từng tin nhắn (D26, D59).
   - Cảnh báo khi bật cloud hoặc Jev, kèm phạm vi dữ liệu đi ra ngoài (D17, D21, D53).
   - Thanh Draft → Publish và phiên bản đang chạy (D20).
   - Dải tin cậy và nhà cung cấp khi thử khớp kịch bản (D22, D29).
   - Tham số Tool **gắn từ token**, khóa lại, LLM không điền được (D32).
   - Guardrail nền tảng và chính sách Organization ở dạng chỉ đọc phía trên Instructions (D19).
   - Phiên bản model được ghim (D18).
3. **Dùng đúng thuật ngữ chính thức** (tong-hop mục 3.3): Organization, Workspace, Assistant, Channel, Collection, Answer Script, Skill, Connector, Tool, Glossary. Không dùng: Co-work, Project, User Manual, Agent, Chatbot (trừ khi nói với người dùng cuối).
4. **Vai trò quyết định thứ người dùng thấy (D48).** Ví dụ Builder không thấy giá trị secret; chỉ Reviewer mở được nội dung hội thoại.
5. **Tiếng Việt là công dân hạng nhất ở phía người dùng cuối:** gõ không dấu, cách xưng hô, câu trộn Việt–Anh (D60).

---

## 3. Doanh nghiệp giả định

**Tên:** Mekong Devworks (giả định, không phải công ty thật).

**Mô tả:** công ty phần mềm khoảng 300 người tại Việt Nam, cung cấp dịch vụ outsource: đội software engineer làm việc theo dự án cho khách hàng nước ngoài (Nhật, Mỹ, châu Âu). Có cổng nội bộ cho nhân viên và trang tuyển dụng công khai.

### 3.1 Assistant và Channel

| Assistant | Channel | Người dùng | Chế độ | Ngôn ngữ chính |
|---|---|---|---|---|
| **Employee Assistant** — hỗ trợ nhân viên về chính sách, quy trình, IT, dự án | Widget trong **cổng nội bộ** (Employee Portal) | Nhân viên đã đăng nhập; nhóm lấy từ token (`all-staff`, `managers`, `project-falcon`…) | Token ký (D11) | Tiếng Việt, tiếng Anh |
| **Careers Assistant** — trả lời ứng viên về công ty, quy trình tuyển dụng, phúc lợi | Widget trên **trang tuyển dụng công khai** | Ứng viên ẩn danh | Ẩn danh có giới hạn (D2, D15) | Tiếng Anh, tiếng Việt |

Hai Assistant thể hiện được: Assistant ↔ Channel (D5), chế độ đăng nhập và ẩn danh (D2), phân quyền tri thức (D8).

### 3.2 Collection (thể hiện D8)

| Collection | Quyền | Nội dung mẫu |
|---|---|---|
| Company & Careers | **Public** | Giới thiệu công ty, quy trình tuyển dụng, phúc lợi chung, FAQ ứng viên |
| Employee Handbook | **Authenticated** | Chính sách nghỉ phép, OT, làm việc từ xa, công tác phí, quy trình onboarding/offboarding |
| IT & Security | **Authenticated** | Hướng dẫn VPN, cấp quyền repo, chính sách bảo mật mã nguồn khách hàng, NDA |
| Engineering Standards | **Authenticated** | Coding convention, quy trình code review, Definition of Done |
| Manager Handbook | **Restricted** — `managers` | Quy trình đánh giá hiệu suất, khung lương, quy trình xử lý kỷ luật |
| Project Falcon (Client: Japan) | **Restricted** — `project-falcon` | Tài liệu dự án dưới NDA: kiến trúc, quy trình release, liên hệ phía khách |

Cờ **"Local model only"** (D17) bật cho Manager Handbook và Project Falcon.

### 3.3 Answer Scripts mẫu

| Kịch bản | Ghi chú |
|---|---|
| IT helpdesk contact | Nguyên văn |
| VPN setup | Nguyên văn, kèm link |
| Payday & payslip | Nguyên văn |
| Office hours & holiday schedule | Có ngày bắt đầu/kết thúc cho lịch nghỉ Tết (D39) |
| Hiring process steps (Careers) | Nguyên văn, song ngữ |
| Talk to HR | Hành động: chuyển người thật (D14, D23) |

Cặp kịch bản **gần nghĩa khác ý** (để minh họa "thử khớp" và dùng cho bộ test spike):
- "How to request leave" / "How to cancel a leave request"
- "OT policy on weekdays" / "OT policy on public holidays"
- "Onboarding checklist" / "Offboarding checklist"
- "Allowance for working at client site" / "Remote work allowance"

### 3.4 Connector, Tool, Skill (thể hiện D31, D32)

| Thành phần | Nội dung |
|---|---|
| Connector | **HR System API** (app giả định của Mekong Devworks), xác thực bằng API key, domain được phép `hr-api.mekongdevworks.example` |
| Tool | `GET /employees/{employee_id}/leave-balance?year={year}` — chỉ đọc. `employee_id` **gắn từ claim `sub`** của token, khóa lại |
| Skill | **Check my leave balance** — kiểu cố định. Khi nào dùng: nhân viên hỏi số ngày phép còn lại. Thông tin cần hỏi: `year` (mặc định năm hiện tại). Mẫu trả lời: "Năm {year}, {tên} còn {annual_remaining} ngày phép năm và {sick_remaining} ngày phép ốm." |
| Skill (Later) | My project allocation; Submit leave request (Tool ghi, cần xác nhận — D34) |

### 3.5 Glossary mẫu (D43)

OT ↔ overtime ↔ làm thêm giờ · PTO ↔ paid time off ↔ nghỉ phép có lương · BHXH ↔ bảo hiểm xã hội ↔ social insurance · DoD ↔ Definition of Done · PM ↔ project manager · onsite ↔ làm việc tại site khách hàng.

### 3.6 Người dùng mẫu

| Tên | Vai trò hệ thống / nhóm | Dùng để minh họa |
|---|---|---|
| Linh Tran | Org Admin | Cài đặt Organization, công tắc cloud/Jev |
| Minh Pham | Builder | Cấu hình Assistant, Publish |
| Thao Nguyen | Knowledge Editor (HR) | Tài liệu, kịch bản, glossary |
| Quang Le | Developer | Connector, Tool, khóa token |
| Hà Vũ | Reviewer | Xem hội thoại, trace |
| An Do | Nhân viên — nhóm `all-staff`, `project-falcon` | Người dùng cuối đã đăng nhập |
| Ứng viên ẩn danh | — | Người dùng cuối trên trang tuyển dụng |

---

## 4. Danh sách màn hình

Nhãn: **P** = trong bản thử; **Later** = vẽ để hình dung, ngoài phạm vi bản thử.

### A. Widget — người dùng cuối

| # | Màn hình | Quyết định thể hiện | Nhãn |
|---|---|---|---|
| A1 | Launcher đóng + mở với lời chào và câu gợi ý (Careers, ẩn danh, tiếng Anh) | D2, D16 | P |
| A2 | Trả lời từ tài liệu có trích dẫn, trạng thái "Searching documents…" khi stream | D17-M1, D26, D57 | P |
| A3 | Trả lời từ Answer Script (nguyên văn) | D23, D25 | P |
| A4 | Skill "Check my leave balance" (nhân viên đã đăng nhập, tiếng Việt, xưng hô) | D31, D32, D60 | P |
| A5 | Không tìm thấy thông tin + phản hồi 👎 kèm lý do + nút "Talk to HR" | D14, D56 | P |
| A6 | Từ chối câu ngoài phạm vi; thông báo giới hạn tần suất (ẩn danh) | D15, D27 | P |
| A7 | Widget trên mobile | D16 | P |
| A8 | Trạng thái bảo trì (Channel bị tắt) và "hệ thống đang bận" | D55, D57 | P |

### B. Trang quản trị (tiếng Anh)

| # | Màn hình | Quyết định thể hiện | Nhãn |
|---|---|---|---|
| B1 | Đăng nhập | D49 (2FA: Later) | P |
| B2 | Khung điều hướng: Organization → Workspace → các mục | Mô hình phân cấp | P |
| B3 | Dashboard cơ bản + câu chưa trả lời được | D59 | P |
| B4 | Danh sách Assistant | D5, D20 | P |
| B5 | Assistant — Instructions (biểu mẫu, 3 tầng, ô xưng hô) + thanh Draft/Publish | D19, D20, D60 | P |
| B6 | Assistant — Model (phiên bản ghim, preset, cảnh báo cloud) | D17, D18 | P |
| B7 | Assistant — Knowledge Scope, Scripts, Skills (cảnh báo xung đột "Local model only") | D5, D17, D24, D31 | P |
| B8 | Playground: giả lập người dùng (ẩn danh / token với nhóm) + **trace 5 bước** | D26, D56, D59 | P |
| B9 | Knowledge — danh sách Collection (nhãn quyền, cờ local only) | D8, D17 | P |
| B10 | Knowledge — chi tiết Collection: folder, tài liệu, trạng thái (kể cả "Scanned PDF not supported"), ô hỏi thử | D9, Module 1 | P |
| B11 | Answer Scripts — danh sách (trạng thái, ngày bắt đầu/kết thúc, số lần khớp) + import CSV | D24, D39 | P |
| B12 | Answer Script — trình soạn + **Test match** (dải tin cậy, điểm, nhà cung cấp local/Jev) | D22, D25, D29 | P |
| B13 | Glossary | D43 | P |
| B14 | Connector — chi tiết (secret che, domain được phép) + Tool (tham số gắn từ token) | D32, D33 | P |
| B15 | Skill — trình soạn kiểu cố định + chạy thử với token | D35 | P |
| B16 | Channels — danh sách + cài đặt (domain, chế độ xác thực, khóa token xoay vòng, giới hạn tần suất) + mã nhúng | D11, D12, D15 | P |
| B17 | Channel — giao diện (màu, avatar, tên, vị trí, sáng/tối) + lời chào, câu gợi ý theo ngôn ngữ + xem trước | D16 | P |
| B18 | Conversations — danh sách (lọc câu chưa trả lời được, 👎) + bản ghi kèm trace từng tin nhắn | D13, D48, D59 | P |
| B19 | Câu chưa trả lời được — gắn nhãn nguyên nhân, hành động (tạo kịch bản, thêm tài liệu) | D44 | P |
| B20 | Organization settings — Model providers (danh mục local có phiên bản, BYOK), công tắc cloud và Jev kèm cảnh báo, chính sách Organization | D17, D18, D19, D21, D53 | P |
| B21 | Organization settings — công tắc khẩn cấp | D55 | P |
| B22 | Members & roles | D48 | P |
| B23 | Audit log | D50 | Later (sự kiện đã ghi từ bản thử, giao diện để MVP) |
| B24 | Usage & quota | D7, D58 | Later |

---

## 5. Canvas thiết kế

**Link:** https://claude.ai/artifact/4YiSppZaEbjh9C5YSMgHUF (riêng tư — người khác chỉ mở được sau khi chia sẻ từ menu Share của trang).

**Hệ thị giác đang dùng (tạm thời, chưa phải design system):** font IBM Plex Sans / IBM Plex Mono (hỗ trợ tiếng Việt); nền #F7F7F8, chữ #16181D; màu nhấn trang quản trị xanh #2346C7; widget dùng màu thương hiệu của khách (teal #0E7C6B, đổi được bằng tweak). Nhãn quyền: Public xanh lá, Authenticated xanh dương, Restricted cam.

| Artboard | Màn hình (mục 4) |
|---|---|
| Main · WidgetNotFound · WidgetCareers · WidgetMobile · WidgetStates | A1–A8 (gộp theo nhóm trạng thái) |
| Sidebar | Thành phần dùng chung cho mọi trang quản trị |
| SignIn · Dashboard · Assistants | B1–B4 |
| AssistantInstructions · AssistantConfig · Playground | B5–B8 |
| Collections · CollectionDetail | B9–B10 |
| Scripts · ScriptEditor · Glossary | B11–B13 |
| Connector · SkillEditor | B14–B15 |
| ChannelSettings · ChannelAppearance | B16–B17 |
| Conversations · Unanswered | B18–B19 |
| OrgSettings | B20–B21 (gộp) |
| Members | B22 |
| — | B23, B24 chưa vẽ riêng; chỉ xuất hiện dưới dạng nhãn "Later" |

### Vấn đề bản vẽ làm lộ ra (chờ quyết định)

| # | Vấn đề | Đề xuất |
|---|---|---|
| V1 | Widget có nút **"Gặp HR"** và kịch bản hành động **"Talk to HR"**, nhưng theo D61 chuyển người thật thuộc MVP, không thuộc bản thử | Đưa bản tối giản (gửi bản ghi hội thoại qua email) vào bản thử — công sức thấp, làm demo trọn vẹn hơn |
| V2 | Cột **nguyên nhân** ở màn hình câu chưa trả lời được thuộc giai đoạn sau (D44) | Giữ nhãn "Later"; bản thử chỉ có danh sách và nhóm câu tương tự |
| V3 | Gom nhóm câu hỏi tương tự ở màn hình câu chưa trả lời được chưa có trong phạm vi bản thử | Bản thử: danh sách thô, chưa gom nhóm |
| V4 | Trang quản trị dùng một sidebar cố định với người dùng là Builder; các màn hình của vai trò khác có nhãn "Viewing as…" | Chấp nhận cho bản mock; giao diện thật ẩn mục theo vai trò |

---

## 6. Lịch sử thay đổi

| Ngày | Thay đổi |
|---|---|
| 2026-10-12 | Tạo file; chốt UI1–UI6; doanh nghiệp giả định Mekong Devworks; danh sách màn hình A1–A8, B1–B24 |
| 2026-10-12 | Vẽ xong 25 artboard trên canvas; ghi nhận vấn đề V1–V4 |
