# Design reference

## Canvas

**https://claude.ai/artifact/4YiSppZaEbjh9C5YSMgHUF** — "ei-ai Prototype UI", 25 artboards, mid-fidelity. Admin UI in English; widget copy in Vietnamese and English. Fictional customer: Mekong Devworks. Read it with the Artifact tool (`action: "read"`), never with WebFetch.

Ticket **DSN-01 (EA-85)** is the hub: artboard → ticket map, visual language, shared UX patterns, design discrepancies X1–X15 and the list of artboards still to draw. Read EA-85 before writing or reviewing a UI ticket.

## Artboards

Main, WidgetNotFound, WidgetCareers, WidgetMobile, WidgetStates, Sidebar, SignIn, Dashboard, Assistants, AssistantInstructions, AssistantConfig, Playground, Collections, CollectionDetail, Scripts, ScriptEditor, Glossary, Connector, SkillEditor, ChannelSettings, ChannelAppearance, Conversations, Unanswered, OrgSettings, Members.

## Writing a Design reference section

1. Name the artboard(s) in bold and link the canvas once.
2. List what the implementer must match: section titles, field labels, options, button labels, badges, empty/error/maintenance states, exact copy (quote it).
3. Say what is tagged **Later** in the artboard and must stay disabled or hidden.
4. Point out any X-item from DSN-01 that changes the artboard for this ticket ("Prototype decision (DSN-01 X4): …").
5. If the screen is not drawn yet, say so, name the existing patterns to reuse, and add it to the "Artboards still to draw" table in EA-85.
6. Add an AC "Matches design: Then … matches the <Artboard> artboard" and a Relates link from EA-85.

## Visual language (summary)

- IBM Plex Sans / IBM Plex Mono.
- Text #16181D; secondary #3F4752 / #555E6B; borders #E1E4E8 / #C9CED4; background #F7F7F8.
- Admin accent #2346C7 (hover #1D3BAA, tint #E8EEFC); widget brand default #0E7C6B (link #0B6B5C).
- Success #1E6B34 on #E6F4EA; warning #8A4205 / #9A4A06 on #FDF0E1.
- Access labels with text, not colour alone; touch targets ≥ 44 px; text contrast ≥ 4.5:1.

## Keeping it current

When the owner resolves an X-item or the canvas changes, update EA-85, `docs/design/design-decisions.md`, and every affected ticket's Design reference in the same pass.
