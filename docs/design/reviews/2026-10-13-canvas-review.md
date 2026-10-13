# Design review — "ei-ai Prototype UI" canvas (2026-10-13)

- **Canvas:** https://claude.ai/artifact/4YiSppZaEbjh9C5YSMgHUF (private; source of truth). Read-only mirror: [../canvas/](../canvas/).
- **Ticket:** DSN-01 (EA-85). **Reviewer:** Lead (design review), on behalf of the project owner.
- **Revision reviewed:** 26 artboards as published before 2026-10-13 (including the owner's new **Chat** artboard). **Revision produced:** 31 artboards (canvas version 29 and later).

## 1. Scope and method

**Baseline.**
- 26 artboards: 5 widget artboards, the Sidebar component, and 20 admin pages.
- This includes the owner's **Chat · Use an assistant** artboard (screen B25).
- The owner's screenshot of that artboard is kept at [../screens/console-chat.png](../screens/console-chat.png).

**References.**
- Decisions D1–D67: [phan-bien-va-quyet-dinh.md](../../workshop/phan-bien-va-quyet-dinh.md).
- Product summary and terminology: [tong-hop.md](../../workshop/tong-hop.md), §3.3.
- [design-decisions.md](../design-decisions.md): screens A1–A8, B1–B25, V1–V4, X1–X20.
- [backlog.md](../../backlog/backlog.md), §8.
- The D67 tickets: EA-88 (WGT-12), EA-89 (FND-13), EA-90 (WGT-13), EA-91 (WGT-14).
- The owner's chat brief, five elements:
  1. chat history (New chat, search, grouped by day);
  2. an assistant picker that shows the live version and the user's groups;
  3. answers with citations and live data cards;
  4. a Sources panel showing the cited passages;
  5. a link to open the same question in the Playground for its trace.

**Heuristics.**
- Consistency of patterns and visual language.
- Information architecture and navigation.
- Completeness of states.
- Accessibility (WCAG 2.2 AA).
- Copy and i18n (EN/VI).
- Terminology (official terms only).
- Role-awareness (D48, D67).
- Coverage of the D-decisions.

**Method.**
1. Manual read of every artboard source.
2. A scripted scan of the canvas: colours, contrast, control sizes, aria-labels, links. Repeatable with [../checks/canvas.test.mjs](../checks/canvas.test.mjs).
3. A contrast computation for every token pair: [../tokens/README.md](../tokens/README.md).

**Severity.**
- **Blocker:** prevents implementation or contradicts a decision with security impact.
- **High:** a missing screen, state or role view that a ticket needs.
- **Medium:** inconsistency or an accessibility gap that would be built wrong.
- **Low:** copy or polish.
- **Info:** observation, no change.

**Status values.**
- Fixed in canvas (rev 2026-10-13).
- Ticket edit (EA-x).
- Owner decision (Xn).
- Fixed in tokens.
- Deferred (reason).

## 2. Summary

**Strengths worth keeping.**
- Every answer carries a **provenance line** ("Searched N collections · M passages", "Verified answer", "Checked HR System"). This is the strongest pattern on the canvas, and it is consistent across the widget, Playground and Chat.
- The "invisible" decisions are made visible:
  - token-bound Tool parameters;
  - the 5-step trace;
  - "Local model only" flags and Later tags;
  - the Draft/Publish bar and pinned model versions.
- The pages use real semantic controls (buttons, labels, selects) and are bilingual where end users meet them.
- The palette is restrained: one admin accent, one widget brand colour and access labels with text. IBM Plex is used consistently.
- The owner's Chat artboard already had the right structure: history, conversation, Sources panel.

**Top issues found (all addressed in this revision or sent to the owner):**
1. The Chat had **no states**: new chat, streaming with Stop, not found, maintenance, rate limit, busy, no assistant, history search (CH-02).
2. **D67 was not drawn** outside the Chat. Missing were:
   - the Member role, knowledge groups and External user ID;
   - the built-in Console chat Channel;
   - the "Available in Console chat" switch;
   - the rated-only reviewer rule (GL-01, GL-02, GL-03).
3. The **Playground link did not carry the question**, so it could not show "its trace" (CH-01).
4. **Members hit dead ends:** the Sources "Open" link went to an admin page, and there was no Member view (CH-03, CH-04).
5. **Accessibility:**
   - form-field borders were 1.58:1, against a 3:1 minimum (GL-06);
   - citation links were 12 px text with no accessible name (CH-08);
   - several 36–40 px targets on end-user surfaces (CH-09, GL-07).

## 3. Findings

| ID | Severity | Area | Artboard(s) | Finding | Recommendation | Status |
|---|---|---|---|---|---|---|
| CH-01 | High | States | Chat, Playground | "Open in Playground" sat in the header and opened an empty Playground, so the owner's "open the same question for its trace" was not possible | Per-answer action that opens the Playground pre-filled with that question, re-run on the live version as the same user, with an "Opened from Chat" banner (X19) | Fixed in canvas (rev 2026-10-13) — PlaygroundFromChat; Owner decision (X19) |
| CH-02 | High | States | Chat | No empty/new chat, streaming + Stop, not found, maintenance, rate limit, busy, no-assistant or history-search states (EA-88 AC7, EA-85 AC6) | One states board covering each state with its exact copy | Fixed in canvas (rev 2026-10-13) — ChatStates |
| CH-03 | High | Role-awareness | Chat, Sidebar | No view for the chat-only Member role (D67 item 1); the Sidebar had no role variant | Member view in Vietnamese; Sidebar `role` and `lang` options | Fixed in canvas (rev 2026-10-13) — ChatMember, Sidebar |
| CH-04 | High | IA / role-awareness | Chat | The Sources "Open" link went to the admin Collection page, a dead end for Members | "Open in Knowledge" only for roles with Knowledge access; others see the quoted passage only (X18) | Fixed in canvas (rev 2026-10-13); Owner decision (X18) |
| CH-05 | Medium | States | Chat | The panel says "for the selected answer" but no answer looked selected | Playground selection pattern: 2 px accent border plus "Selected · sources on the right"; panel heading names the question | Fixed in canvas (rev 2026-10-13) |
| CH-06 | Medium | Consistency | Chat | The Skill answer had no 👍/👎/copy actions, and what the panel shows for a Skill answer was undefined | Same action row under every answer; a data-source card for Skill answers (ChatMember) | Fixed in canvas (rev 2026-10-13) |
| CH-07 | Medium | IA | Chat | The picker was a native select with no per-option live version or reason for listing; Careers Assistant conflicted with EA-90 AC3 | Open-picker state with live version per Assistant and "Listed because of your groups"; sample data: Careers enabled for people-ops only | Fixed in canvas (rev 2026-10-13); Ticket edit (EA-90) |
| CH-08 | Medium | Accessibility | Chat | Citations `[1]` were 12 px text links with no accessible name | 24×24 px chips with `aria-label="Source N: <title>"` | Fixed in canvas (rev 2026-10-13) |
| CH-09 | Medium | Accessibility | Chat, ChatStates | Answer actions are 40×36, chips 36 and select/input 40 px on an end-user surface | 44×44 px hit area on end-user surfaces, visible size may stay smaller (X16) | Owner decision (X16) |
| CH-10 | Medium | Content model | Chat, ChannelConsoleChat | Where the console greeting and suggestion chips come from was undefined (WGT-06 per Channel vs EA-88 AC6 per Assistant) | Console chat Channel holds greeting and suggestions per Assistant, EN/VI (X20) | Owner decision (X20); Fixed in canvas (rev 2026-10-13) — ChannelConsoleChat |
| CH-11 | Medium | States | ChatStates | A console "not found" answer had no hand-off, while "Talk to HR" (WGT-11) is widget-only | No hand-off in the console for the prototype; follow the Assistant's not-found text | Ticket edit (EA-50) |
| CH-12 | Low | i18n | Chat | Chat chrome existed only in English, although Members are end users (EA-88 AC9) | Draw the Member view with Vietnamese chrome to prove the strings fit | Fixed in canvas (rev 2026-10-13) — ChatMember |
| CH-13 | Low | Copy | Chat | History meta showed a time for Today but nothing for Yesterday or older | Time for Today and Yesterday, date for older items | Fixed in canvas (rev 2026-10-13); Ticket edit (EA-91) |
| CH-14 | Low | Accessibility | ChatStates | No live region described for streamed text and status | Annotate a polite `aria-live` region and the Stop button | Fixed in canvas (rev 2026-10-13) |
| CH-15 | Low | Copy | Chat | Meaning of N and M in "Searched N collections · M passages" was undefined | N = collections that contributed passages after reranking; M = passages sent to the model | Ticket edit (EA-88) |
| CH-16 | Info | Content | Chat | Relevance scores (0.89) mean little to Members | Keep per EA-88; revisit with usage data | Deferred (after prototype feedback) |
| CH-17 | Low | Consistency | Chat, ChatMember, ChatStates | The Assistant avatar "EA" uses the widget brand teal #0E7C6B inside the admin console, with no rule for where the colour comes from | Avatar colour comes from the Assistant (initials on a per-Assistant colour, default admin accent); record it when ADM-01 builds Assistant identity | Deferred (ADM-01 Assistant identity) |
| CH-18 | Low | Consistency | Chat | The "Open in Playground" secondary button keeps the light #C9CED4 border while the fields beside it use #8A929C | Keep #C9CED4 for secondary buttons (their text label identifies them); the darker border is reserved for fields so they read as inputs | Deferred (by design, documented in tokens) |
| GL-01 | High | D67 coverage | Members | Members lacked the Member role, knowledge groups, External user ID and the Chat/Playground rows of the role matrix | Add the Member column, Knowledge groups and External user ID with help text | Fixed in canvas (rev 2026-10-13) |
| GL-02 | High | D67 coverage | ChannelSettings, AssistantConfig, OrgSettings, Assistants, AssistantInstructions | No built-in Console chat Channel, no "Available in Console chat" switch, no Console chat emergency switch (D55); "Live on" lines omitted Console chat | Built-in channel row and detail page; switch with "who can use it"; emergency switch row; Live-on lines updated | Fixed in canvas (rev 2026-10-13) — ChannelConsoleChat |
| GL-03 | Medium | D67 coverage | Conversations | The rated-only rule for console chats was not shown, and the "Token groups" label is wrong for console chats | Channel filter and note "Console chat: rated conversations only"; label "Groups" | Fixed in canvas (rev 2026-10-13) |
| GL-04 | High | Identity consistency | Connector, SkillEditor, Members | An Do's HR ID was emp-0421 on the canvas and E-1042 in the tickets; Minh Pham had no External user ID; Connector did not say where the console identity comes from | One sample ID per person (An Do emp-0421, Minh Pham emp-0107) and a note that console identity comes from the member's External user ID | Fixed in canvas (rev 2026-10-13); Ticket edit (EA-89, EA-90, EA-65) |
| GL-05 | High | Flow | WidgetNotFound, ChannelSettings | "Gặp HR" sent the transcript with no confirmation, there was no daily-limit state, and ChannelSettings still said Later (X6) | Confirmation step with what is sent and to whom, plus the 3-per-day limit state; remove the Later tag | Fixed in canvas (rev 2026-10-13) — WidgetHandoff |
| GL-06 | Medium | Accessibility | All pages with fields | Form-field borders #C9CED4 are 1.58:1 on white (WCAG 1.4.11 needs 3:1) | Token `color.border.field` #8A929C (3.15:1) on input, select, textarea and the composer frame (X17) | Fixed in canvas (rev 2026-10-13); Owner decision (X17) |
| GL-07 | Medium | Accessibility | Main, WidgetNotFound, WidgetMobile | Widget feedback buttons 44×36, chips 36 px, "Gửi phản hồi" 40 px | Same hit-area rule as CH-09 (X16) | Owner decision (X16) |
| GL-08 | Low | Copy accuracy | ChannelAppearance | The contrast indicator said 5.3:1; the computed value is 5.10:1 | Show the computed ratio, 5.1:1 | Fixed in canvas (rev 2026-10-13); Ticket edit (EA-46) |
| GL-09 | Low | Contrast | Sidebar, Chat | The muted label colour #6B7380 is 4.47:1 on #F7F7F8 (below 4.5:1) | Use it on white surfaces only; token rule in the README | Fixed in tokens |
| GL-10 | Medium | Scope labels | Unanswered, CollectionDetail | Similarity grouping (X4) and the .doc row (X1) carried no Later tag (principle 1) | Add Later tags | Fixed in canvas (rev 2026-10-13) |
| GL-11 | Medium | Decision D18 | OrgSettings | "Stop all external AI" said "local models take over" (X13) | Cloud-model Assistants show "temporarily unavailable"; no automatic model switch | Fixed in canvas (rev 2026-10-13) |
| GL-12 | Low | Copy | SignIn | "Manage your organization's assistants" excludes Members; the 2FA note said "Owner, Admin" while D49 names Org Owner, Org Admin and Developer; Members should land on Chat | Neutral sign-in copy, correct 2FA roles, Member landing page | Fixed in canvas (rev 2026-10-13); Ticket edit (EA-89) |
| GL-13 | Low | Copy | Collections | "Restricted · token includes one of the listed groups" ignores console groups (D67) | "the user's groups include one of the listed groups" | Fixed in canvas (rev 2026-10-13) |
| GL-14 | Info | Consistency | All | About 50 distinct hex values, including one-off tints | Consolidated into tokens with a map of legacy values | Fixed in tokens |
| GL-15 | Info | IA | Sidebar | "Skills & Connectors" opens the Skill editor directly (no Skills list); acceptable with one Skill | Add a list when a second Skill exists | Deferred (one Skill in the prototype) |
| GL-16 | Info | Naming | Main, Chat | The widget shows the Channel display name "Mekong Assistant" while Chat shows the Assistant name "Employee Assistant" | Intentional: Channel appearance vs Assistant; do not change | Deferred (by design) |
| GL-17 | Low | Decision D58 | Dashboard | The "By assistant" table has no Console chat row | Add a channel split when ADM-08 is built | Deferred (ADM-08 build; totals change) |
| GL-18 | Medium | Scope | Conversations | "Search messages" implied full-text search (X14) | Placeholder "Search first questions" | Fixed in canvas (rev 2026-10-13) |
| GL-19 | Medium | Decision D20 | AssistantInstructions | Layer 2 (Organization policy) did not say that changes apply immediately (X15) | State "Changes apply immediately to every assistant" | Fixed in canvas (rev 2026-10-13); Owner decision (X15) |

## 4. Console Chat deep-dive

How each element of the owner's chat brief stood before this revision, what was missing, and what was drawn.

| Element | Before | Gaps | Drawn in this revision |
|---|---|---|---|
| 1. Chat history (New chat, search, grouped by day) | New chat, search box, Today / Yesterday / Previous 7 days groups | No search state; inconsistent meta; no empty state | Times and dates on every item (Chat); "History search" with results and clear button, plus "New chat — empty" (ChatStates) |
| 2. Assistant picker with live version and groups | Native select, "Live v7" badge, "Answering as Minh Pham · all-staff, people-ops" | No per-option version; no reason for listing; no "no assistant" case | "Assistant picker — open" with live version per Assistant and "Listed because of your groups"; "No assistant available" (ChatStates); describedby link to the identity line (Chat) |
| 3. Answers with citations and live data cards | RAG answer with `[n]` links; Skill answer with leave cards and data footnote | Unnamed tiny citation links; no actions on the Skill answer; no streaming or not-found state | 24 px citation chips with accessible names; action row on every answer; "Streaming — stop" and "Not found" (ChatStates); Vietnamese Member version (ChatMember) |
| 4. Sources panel with cited passages | Two source cards, "Open" link to an admin page | No visible selected answer; dead-end link for Members; no Skill-answer case | Selected-answer pattern; heading names the question; "Open in Knowledge" for Knowledge roles only; data-source card for a Skill answer (ChatMember) |
| 5. Link to open the same question in the Playground for its trace | Header link to an empty Playground | Did not carry the question; no role rule | Per-answer "Open in Playground" for Builders and Workspace Admins; PlaygroundFromChat shows the same question re-run on the live version with "Opened from Chat" and the 5-step trace |

## 5. Decision coverage

| Decision | Artboard(s) | Coverage |
|---|---|---|
| D2 signed-in first, anonymous limited | Main, WidgetCareers | Covered |
| D8 three access levels, filter before the model | Collections, Chat (Sources footer) | Covered |
| D11 host-signed token | ChannelSettings | Covered |
| D13 history 90 days, separate review permission | Chat, Conversations, Members | Covered (rated-only for console, D67) |
| D14 minimal hand-off | WidgetNotFound, WidgetHandoff | Covered |
| D16 appearance per Channel | ChannelAppearance | Covered |
| D17 local by default, cloud opt-in | AssistantConfig, OrgSettings | Covered |
| D18 pinned version, no fallback | AssistantConfig, OrgSettings | Covered (X13 fixed) |
| D19 three-layer instructions | AssistantInstructions | Covered (X15 pending) |
| D20 Draft / Publish | AssistantInstructions, Chat ("Live v7") | Covered |
| D26 five-step pipeline and trace | Playground, PlaygroundFromChat, Conversations | Covered |
| D31 fixed-flow Skill | SkillEditor, Chat | Covered |
| D32 identity bound server-side | Connector, SkillEditor, Members | Covered (sample IDs aligned, GL-04) |
| D48 fixed roles | Members, Sidebar | Covered |
| D49 2FA roles | SignIn | Covered (copy fixed, GL-12) |
| D55 emergency switches | OrgSettings, ChatStates (maintenance) | Covered |
| D57 latency and busy states | WidgetStates, ChatStates | Covered |
| D59 trace and unanswered list | Playground, Unanswered | Covered |
| D60 Vietnamese first-class | Main, ChatMember | Covered |
| D67 console Chat | Chat, ChatStates, ChatMember, PlaygroundFromChat, ChannelConsoleChat, Members, AssistantConfig, Conversations, OrgSettings, Sidebar | Covered |

## 6. Changes in this revision

- **New artboards (5):**
  - **ChatStates:** new chat, picker open, streaming with Stop, not found, maintenance, rate limit, busy, no assistant, history search.
  - **ChatMember:** Member view in Vietnamese.
  - **PlaygroundFromChat:** the same question, re-run, with its trace.
  - **ChannelConsoleChat:** the built-in channel.
  - **WidgetHandoff:** "Talk to HR" confirmation and the daily limit.
- **Extended artboards:**
  - Chat, Sidebar (role and language variants), Members.
  - ChannelSettings, AssistantConfig, AssistantInstructions, Assistants, Conversations, OrgSettings.
  - Collections, CollectionDetail, Unanswered, Connector, SkillEditor, ChannelAppearance, SignIn.
  - Main, WidgetNotFound, WidgetMobile, Glossary, ScriptEditor.
  - The field border (X17) is applied wherever there are fields.
- **Repo:**
  - design tokens and contrast table: [../tokens/](../tokens/);
  - canvas checks: [../checks/](../checks/);
  - read-only canvas mirror: [../canvas/](../canvas/);
  - X1–X20 decisions: [../design-decisions.md](../design-decisions.md) §6.

## 7. Decisions for the owner

**Confirmed by the owner on 2026-10-13: every recommendation below is accepted** and recorded as Decided in [design-decisions.md](../design-decisions.md) §6.

| # | Question | Recommendation |
|---|---|---|
| X9 | Access levels on Answer Script sets | Same 3 levels as Collections |
| X15 | Organization policy (layer 2) outside Draft/Publish | Applies immediately, as stated on the canvas |
| X16 | Target size | 44×44 px hit area on end-user surfaces (widget, Chat); 24×24 px minimum in admin |
| X17 | Field border | #8A929C (3.15:1) for input, select, textarea and the composer |
| X18 | Sources link | "Open in Knowledge" for Knowledge roles only; others see the passage |
| X19 | Playground link from Chat | Per answer, Builder and Workspace Admin only, re-run on the live version with "Opened from Chat" |
| X20 | Console greeting and suggestions | Per Assistant in the Console chat Channel, EN/VI |

## 8. Follow-ups

- **MVP artboards still to draw** (EA-85 follow-up table):
  - 2FA enrolment and code entry (MVP-01);
  - audit log viewer (MVP-02);
  - usage and quota with the widget "limit reached" state (MVP-03);
  - end-user data deletion (MVP-04);
  - rollback in version history (MVP-07);
  - Organization theme with inherited/overridden tags (MVP-08).
- Dashboard channel split for Console chat (GL-17, with ADM-08).
- Assistant avatar colour rule (CH-17, with ADM-01).
- Re-check X16 hit areas once the frontend exists (SET-03 token import, EA-13).
