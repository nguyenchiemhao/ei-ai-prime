# Canvas mirror (read-only)

A read-only copy of the files of the design canvas **"ei-ai Prototype UI"**: one `.dc.html` file per artboard, plus `canvas.json` (layout and order).

- **Source of truth:** the private claude.ai canvas, https://claude.ai/artifact/4YiSppZaEbjh9C5YSMgHUF. Never edit these files by hand.
- **Refresh:** a design ticket (DSN-xx) publishes its changes to the canvas, then copies the same files here in the same commit.
- **Use:** implementers and AI agents read the artboards here without access to the private canvas (EA-85, open question 2). Open an artboard source to see exact copy, states and styles.
- **Check:** `node --test docs/design/checks/canvas.test.mjs` validates these files and the design docs.
