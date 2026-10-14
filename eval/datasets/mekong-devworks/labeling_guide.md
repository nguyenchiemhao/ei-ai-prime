# Labelling guide — Mekong Devworks test set

Version 1.2 (2026-10-14). Version 1.0 was the initial text; 1.1 added the task and own-value rules; 1.2 reworded every example (rules unchanged). Everything in this folder is fictional (see `README.md`).

## 1. Purpose and who uses the labels

Every test question carries two labels: a **type** (what kind of message it is) and a **correct script** (which Answer Script should be returned, or `NONE`). The labels are the ground truth for:

- **PIPE-02 (Classifier):** accuracy per type, and the false `out_of_scope` rate (target < 1%); group G follow-up detection (target > 80%).
- **EVL-04 (Script Matcher spike):** top-1 / top-3 script accuracy, precision when the answer is `NONE`, break-downs for groups B, C and H.
- **JEV-04 (Jev spike):** the same set measures the local model against the cloud model.

A label is wrong when a reasonable HR / IT / recruiting colleague at Mekong Devworks would disagree with it. When two labellers disagree, the definition in this guide is fixed first (see section 8).

## 2. Record format

`test_questions.jsonl` has one JSON object per line.

| Field | Meaning |
|---|---|
| `id` | A unique code `q-NNNN`. |
| `group` | `A` ... `H` (section 6). |
| `language` | `en` or `vi`: the language of `question`. |
| `history` | Array of 0-2 earlier turns, each `{"user": "...", "assistant": "..."}`. Empty (`[]`) for every group except G. |
| `question` | The text the user types. |
| `type` | One of the 7 types in section 3. |
| `correct_script` | A script `id` from `scripts.jsonl`, or `NONE`. |
| `source` | `llm-draft` (drafted by a model, to be reviewed by a person) or `human`. Extra field, not part of the minimum format. |

Mapping to the Vietnamese field names in `docs/workshop/jev-spike.md` section 3.3: `group` = `nhom`, `language` = `ngon_ngu`, `history` = `lich_su`, `question` = `cau_hoi`, `type` = `loai`, `correct_script` = `kich_ban_dung`.

One example line per group (illustrative only; these lines are not in the data set):

```json
{"id":"q-0000","group":"A","language":"en","history":[],"question":"Which page of the portal lists the open design roles?","type":"information","correct_script":"careers-apply","source":"llm-draft"}
{"id":"q-0000","group":"B","language":"vi","history":[],"question":"van phong da nang nam o quan nao","type":"information","correct_script":"office-locations","source":"llm-draft"}
{"id":"q-0000","group":"C","language":"en","history":[],"question":"My hours are right but I forgot to press the final button, where is it?","type":"information","correct_script":"timesheet-submit","source":"llm-draft"}
{"id":"q-0000","group":"D","language":"en","history":[],"question":"What is the severance pay for senior engineers?","type":"information","correct_script":"NONE","source":"llm-draft"}
{"id":"q-0000","group":"E","language":"vi","history":[],"question":"Dịch giúp mình đoạn văn này sang tiếng Nhật","type":"out_of_scope","correct_script":"NONE","source":"llm-draft"}
{"id":"q-0000","group":"F","language":"en","history":[],"question":"Greetings, assistant!","type":"greeting","correct_script":"NONE","source":"llm-draft"}
{"id":"q-0000","group":"G","language":"vi","history":[{"user":"Phòng họp tầng 3 có máy chiếu không?","assistant":"Có, mỗi phòng họp đều có máy chiếu."}],"question":"còn micro thì sao?","type":"follow_up","correct_script":"NONE","source":"llm-draft"}
{"id":"q-0000","group":"H","language":"vi","history":[],"question":"Mình là Vũ Thị Hà, mã emp-0777, cho hỏi văn phòng Hà Nội mở cửa lúc mấy giờ","type":"information","correct_script":"office-hours","source":"llm-draft"}
```

`NONE` means: no script in `scripts.jsonl` is the right reply.

## 3. The seven types

The English names are used in the data and by PIPE-02. D27 names them in Vietnamese; both are listed.

| Type | D27 name | Definition |
|---|---|---|
| `greeting` | `chao_hoi` | A pure greeting or pleasantry with no request. |
| `handoff` | `chuyen_nguoi` | An explicit request to talk to a person (HR, IT helpdesk, a recruiter, "a real human"). |
| `out_of_scope` | `ngoai_pham_vi` | Universally off-topic: has nothing to do with any company (code, maths, translation of unrelated text, general trivia, scraping). |
| `follow_up` | `tiep_noi` | A message that cannot be understood without the earlier turns of the conversation. Only possible when `history` is not empty. |
| `information` | `thong_tin` | How-to, policy or general company facts. This is the default. |
| `task` | `tac_vu` | The user asks the assistant to **do** or change something (submit, cancel, reset, book), or states what they want done without asking how. |
| `data` | `du_lieu` | The user asks for **their own** personal or live record values (balance, amount, hours, status). |

Examples (two English, two Vietnamese each):

- `greeting`: "Hello again!", "Hi, hope you are well!" / "Chào nhé", "Dạ chào bạn ạ".
- `handoff`: "Could a team member take over this chat?", "Please bring in a live colleague." / "Bạn gọi giúp mình một đồng nghiệp hỗ trợ nhé", "Mình muốn trao đổi trực tiếp với một nhân viên".
- `out_of_scope`: "Debug my JavaScript loop.", "Plan a three-day trip to Paris for me." / "Giải thích giúp mình định luật Newton", "Ai thắng giải Oscar năm ngoái?".
- `follow_up` (with history): "and the second option?", "what if it happens twice?" / "thế còn trường hợp thứ hai?", "nếu lặp lại lần nữa thì sao?".
- `information`: "Which floor is the pantry on?", "How do I get a visitor badge for my parents?" / "Phòng họp lớn nhất ở tầng mấy?", "Công ty có tổ chức du lịch hàng năm không?".
- `task`: "Please renew my building access card.", "Sign me up for the Friday football match." / "Giữ giúp mình một chỗ trong buổi chạy bộ sáng thứ Bảy", "Gia hạn thẻ gửi xe của mình đi".
- `data`: "How many training hours have I completed?", "What is my current seat number?" / "Mình đã tham gia bao nhiêu buổi đào tạo rồi?", "Chỗ ngồi hiện tại của mình là số mấy?".

## 4. Precedence rules

When more than one type seems to fit, take the first that applies:

1. `greeting` or `handoff`, only if the whole message is a greeting, or the message explicitly asks for a human. A greeting followed by a real question is **not** a greeting: "Hello! Where is the pantry?" is `information` (the question wins).
2. `follow_up`, only if the message cannot be understood without `history`. If it is understandable alone, label it by its content, even when `history` exists.
3. `out_of_scope`, only if the request is off-topic for every company. A question about Mekong Devworks that no script answers (for example severance pay) is **not** out of scope: it is `information` with `NONE`.
4. `data`, if the user asks for their **own** record values, such as a balance, an amount, hours or a status. Asking for a rule ("how is seniority pay calculated?") is not data.
5. `task`, if the user asks the assistant to perform or change something, or states what they want or need done (or makes a bare request) without asking how, where, when or who: "Please renew my building access card", "I want my seat moved next to the window", "Mình cần đặt trước một chỗ đỗ xe cho thứ Ba", "xin thêm một bàn phím". Once the message asks how, where, when, who or what ("I want my seat moved, who do I ask?", "How do I renew my access card?"), or only whether something is possible ("Can the booking be moved to Thursday?"), it is `information`. "I want to know ..." / "muốn biết ..." asks for information, not for an action.
6. Otherwise `information`.

Personal details in the message (a name, phone number, employee code) never change the type; the question itself decides.

## 5. The `correct_script` rule

- Choose the script that a reasonable HR / IT / recruiting colleague would send as the helpful reply. It is not required that the script answers every word of the question.
- For a `task` question the same rule applies: the label is the script that explains how to do the thing the user asks for, or `NONE` when no script does.
- For a `data` question (the user's own value), choose the script that tells the user where to look the value up or whom to ask, if the catalogue has one for that kind of record. If no script tells the user where to find the value (for example completed training hours, a seat assignment or an attendance record), the label is `NONE`: a Skill or the HR system would answer.
- If no script addresses the core need, use `NONE` (group D). Examples: severance rules, the date of a client's next release, the user's own attendance record (a Skill, not a script).
- Handoff intent is always `NONE` (group F). The script `talk-to-hr` is never a test target.
- Group C: the question is confusable with the partner script (shared words). Label the script that fits the **intent**, not the shared words.
- The `status` and the dates of a script do not matter for labels. A draft or expired script is still the right label if it answers the question.
- Types `greeting`, `handoff`, `out_of_scope` and `follow_up` always have `correct_script` `NONE`.

## 6. Groups A-H

Targets follow `docs/workshop/jev-spike.md` section 3.2. The real total is 430 (see `README.md`).

| Group | Name | Count | EN | VI | `correct_script` | `type` |
|---|---|---|---|---|---|---|
| A | Paraphrase | 120 | 70 | 50 | a script id | mostly `information`, some `task` / `data` |
| B | Unaccented / abbreviations (Vietnamese only) | 60 | 0 | 60 | a script id (at least 20 different scripts) | mostly `information` |
| C | Near-duplicate, different intent | 60 | 35 | 25 | a pair member | mostly `information`, some `task` |
| D | Related, but no script | 60 | 35 | 25 | `NONE` | `information`, `data`, `task` |
| E | Out of scope | 30 | 15 | 15 | `NONE` | `out_of_scope` |
| F | Greeting / handoff | 30 | 15 | 15 | `NONE` | 15 `greeting`, 15 `handoff` |
| G | Follow-up (1-2 history turns) | 40 | 25 | 15 | `NONE` | `follow_up` |
| H | Contains fake personal data | 30 | 20 | 10 | a script id | as A / C |

- **A** keeps the intent of one script but changes the wording. Every script except `talk-to-hr` has at least 2 group A questions.
- **B** is typed the way people type quickly: no diacritics, abbreviations (`ntn`, `k`, `dc`, `nv`, `wfh`, `ot`).
- **C** shares vocabulary with the partner script (for example "leave", "OT", "checklist") while asking for the other thing. Each of the 18 pair members has at least 2 questions.
- **D** is about the company, but only a KB document or a Skill could answer.
- **E** has nothing to do with the company.
- **F** is a pure greeting or an explicit request for a person.
- **G** is elliptical and needs the 1-2 turns of history; the history is about a script topic or a KB topic.
- **H** is an A / C style question that adds a fake phone number, email, ID number, employee code or name.

What to avoid in all groups:

- Copying or lightly editing a script example question or title. A test question must differ from every example and title after normalisation (lower case, no diacritics, no punctuation, single spaces). The validator checks this.
- Using personal data that is not in `fake_personal_data.json` (section 7).
- Facts that contradict the company facts table in `README.md`.

## 7. Fake personal data rules

All personal data is invented and sits in `fake_personal_data.json`; the validator rejects anything else.

- Phone numbers: Vietnamese formats only. Mobile `0[35789]` + 8 digits or `+84[35789]` + 8 digits; landline `02` + 9 digits. Spaces and dots are allowed.
- ID numbers: CCCD has 12 digits, a province prefix from `001, 031, 048, 079, 092` and a century digit 0-3; CMND has 9 digits.
- Employee codes: `emp-` + 4 digits (`emp-0042`).
- Emails: only on reserved domains (`*.example`, `example.com`, `example.org`, `example.net`). URLs: only on `*.example`. Emails are checked by domain only; the registry lists the emails used, for reference.
- Numbers may be written with spaces, dots, hyphens or brackets. Money amounts followed by `đ`, `đồng` or `VND` are not treated as personal data.
- Names are listed in the registry. Vietnamese group H questions use names with diacritics, family name first ("Nguyễn Văn Bình"), as the harder masking case.
- Every phone and ID number used anywhere must be listed in the registry. Amounts like `15.000.000` have fewer than 9 digits and are not treated as personal data.
- Limitation: Vietnam has no reserved fictional phone range, so a made-up number may belong to a real person. The numbers are never dialled.

## 8. Cross-labelling procedure

1. 100 questions are drawn with a fixed seed. Their order is shuffled and every row gets an opaque key (`r-001` ... `r-100`). The map from key to question id is kept apart and is never given to a labeller.
2. `cross_labelling/blind_sheet.csv` shows each sampled question with its key, language and history, but **not** its id, group or labels.
3. Each labeller fills `type` and `correct_script` using only this guide and the script catalogue (id, title, example questions), and writes a file with the columns `key,type,correct_script,note`. Values must match exactly: lower-case type names, a script id from the catalogue or `NONE`. A labeller must not look at `test_questions.jsonl` or at another labeller's file.
4. `tools/cross-labelling.mjs agreement` checks both files (no blank, unknown or duplicate rows), joins them through the key map and reports percent agreement and Cohen's kappa for `type`, `correct_script` and both.
5. For each disagreement decide one of three outcomes:
   - **definition change:** this guide was unclear. Change the guide, add a row to the change log below naming the question ids, and relabel every question in the full set that the new wording affects;
   - **label fix:** the data set label is wrong under the current guide: correct it;
   - **keep:** the other labeller was wrong: record a one-line reason.
6. Record every outcome in `agreement_report.md`. Fix the definition, not just the question.

## Change log

| Date | Section | Change | Triggered by (question ids) |
|---|---|---|---|
| 2026-10-13 | all | Initial version | none |
| 2026-10-14 | 3, 4 (rule 5) | A statement of what the user wants done, or a bare request, without a how/where/when/who question is `task`; "can it be done?" questions and "I want to know ..." stay `information` | review R1-2: q-0159, q-0161, q-0162, q-0182, q-0217, q-0223, q-0427 |
| 2026-10-14 | 5 (`correct_script`) | A question about the user's own value gets the script that tells where to look it up, otherwise `NONE` | review R1-3: q-0027, q-0268, q-0292 |
| 2026-10-14 | 2-5, 7 (examples) | Every example reworded so that none copies, translates or nearly copies a test question; the rules are unchanged (version 1.2) | review R2-1: wording only, no question relabelled |
