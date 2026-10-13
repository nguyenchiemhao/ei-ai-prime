# Design tokens (DSN-01)

`design-tokens.json` holds the visual language of the ei-ai prototype: colours, fonts, radii, spacing and sizes. It is **provisional, not a design system** (UI6). Every value is copied from the canvas in `docs/design/canvas/` (the claude.ai canvas is the source of truth). EA-85 owns this file until SET-03 moves it.

## Format

[W3C Design Tokens](https://www.designtokens.org/) (DTCG): every token is `{ "$value": …, "$type": … }`; a group may set `$type` for its children; `{color.accent.hover}` is a reference to another token. Token paths are written without the `color.` prefix in the tables below (`text.muted` is `color.text.muted`).

## How the file is used

- **Now:** a reference for designers and for AI coding agents. `docs/design/checks/tokens.test.mjs` validates the file and this README.
- **SET-03 (EA-13):** `git mv` the file into the shared frontend token package, compile it to CSS custom properties, and import the variables in the admin UI and in the widget. Components use the variables only; a lint rule or test fails on hard-coded hex colours (coding rules §2, "Frontend styling"). The contrast check below moves into CI there (ADR-001 §3.8).

## Rules

1. **Target size (X16).** End-user surfaces (widget, Chat) need a 44x44 px hit area (`size.target.min`). The visible control may be 36-40 px if padding or a pseudo-element extends the hit area. Admin desktop controls need at least 24x24 px (`size.target.inline-min`, WCAG 2.2 SC 2.5.8). Inline citation chips are at least 24x24 px.
2. **Form-field border (X17).** `input`, `select`, `textarea` and the Chat composer frame use `border.field` (#8A929C, 3.15:1 on white, WCAG 1.4.11). `border.strong` (#C9CED4, 1.58:1) is for decorative outlines and secondary buttons only.
3. **`text.subtle` (#6B7380)** is for group labels on white (#FFFFFF) or #FBFBFC surfaces only. On the page background #F7F7F8 it is 4.47:1 and fails 4.5:1 (use `text.muted`).
4. **Brand colour is customer-configurable per Channel** (WGT-07). The `brand.*` tokens are the Mekong Devworks sample values. Any Channel colour must show the contrast indicator of WGT-07 (white text on the brand colour at least 4.5:1).
5. **Access labels** reuse status colours: Public = success, Authenticated = accent, Restricted = warning (`color.access.*`).

## Contrast (AC4)

WCAG 2.x relative-luminance contrast. The check recomputes every row; a row fails if the computed ratio differs from the stated one by more than 0.01 or is below its minimum. Minimum 4.5 is for text (3 for text from 24 px; not used here), 3 is for non-text elements (WCAG 1.4.11).

| Foreground | Background | Ratio | Minimum | Used for |
|---|---|---|---|---|
| `text.primary` | `surface.card` | 17.76 | 4.5 | Body text on cards and the Chat column |
| `text.primary` | `surface.page` | 16.59 | 4.5 | Body text on the page background |
| `text.secondary` | `surface.card` | 9.40 | 4.5 | Secondary text, quoted passages |
| `text.secondary` | `surface.muted` | 8.23 | 4.5 | Badges (Built-in, Later) |
| `text.muted` | `surface.card` | 6.56 | 4.5 | Captions and meta lines on cards |
| `text.muted` | `surface.page` | 6.13 | 4.5 | Captions on the page background |
| `text.muted` | `surface.subtle` | 6.35 | 4.5 | Captions in the history and Sources panels |
| `text.muted` | `surface.widget-canvas` | 6.12 | 4.5 | Captions inside the widget |
| `text.subtle` | `surface.card` | 4.78 | 4.5 | Group labels on white |
| `text.subtle` | `surface.subtle` | 4.63 | 4.5 | Group labels in the history panel |
| `text.on-accent` | `accent.default` | 7.58 | 4.5 | Primary buttons, user message bubbles |
| `accent.default` | `surface.card` | 7.58 | 4.5 | Links on white |
| `accent.hover` | `accent.tint` | 8.00 | 4.5 | Active sidebar item, citation chips |
| `accent.hover` | `accent.chip-bg` | 8.46 | 4.5 | Suggestion chips, data cards |
| `text.on-accent` | `brand.default` | 5.10 | 4.5 | Widget header, send button, launcher |
| `brand.text` | `surface.card` | 6.42 | 4.5 | Brand-coloured links in the widget |
| `brand.text` | `brand.tint` | 5.92 | 4.5 | Brand-coloured text on the tinted widget surface |
| `status.success.text` | `status.success.bg` | 5.76 | 4.5 | Live version, Public label, On badge |
| `status.warning.text` | `status.warning.bg` | 6.54 | 4.5 | Restricted label, warnings |
| `status.warning.strong` | `status.warning.bg` | 5.58 | 4.5 | Rate-limit banner icon and text |
| `status.warning.deep` | `status.warning.bg` | 8.61 | 4.5 | Emphasis inside warning banners |
| `text.on-code` | `surface.code` | 14.73 | 4.5 | Code and prompt blocks |
| `text.nav` | `surface.card` | 13.27 | 4.5 | Inactive sidebar items |
| `border.field` | `surface.card` | 3.15 | 3 | Field borders, composer frame |
| `accent.default` | `surface.card` | 7.58 | 3 | Focus ring, selected-answer border |

Known failing pair (not used): `text.subtle` on `surface.page` = 4.47, `border.strong` on `surface.card` = 1.58 (decorative only).

## Canvas one-off colours mapped to the nearest token

The canvas has about 50 distinct hex values. These one-off values are not tokens; use the nearest token in code.

| Canvas value | Used for | Use token |
|---|---|---|
| `#F3FAF6` | Script Editor: tinted match-result card | `status.success.bg` |
| `#8CC9A0` | Script Editor: confidence-band bar | `status.success.text` (decorative bar) |
| `#F1F3F5`, `#F4F5F7`, `#F1F2F4` | Neutral fills (skeleton block, info notes) | `surface.muted` |
| `#E3E6EA` | Skeleton bar | `surface.muted` |
| `#CDD2D7` | Typing-indicator dot | `border.strong` (decorative) |
| `#8A929C` | Typing-indicator dot (also the new field border) | `border.field` |
| `#B85A0B`, `#7A3FB0` | Dashboard bars (data series, 8% fill) | none; chart colours are set when the Dashboard is built (ADM-08) |
| `#AEB5BD` | Disabled Send button fill (disabled controls are exempt from WCAG 1.4.3) | none; use `border.strong` |
| `#F3D46B`, `#7A3FB0` | Swatch options in the Channel appearance colour picker (sample data, not UI colours) | none |

## Run the check

```
node --test docs/design/checks/tokens.test.mjs
```

Node 22, no dependencies. Mutation check: point `TOKENS_FILE` or `TOKENS_README` at a modified copy.
