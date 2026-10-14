import { describe, expect, it } from "vitest";
import main from "./main.tsx?raw";

describe("main entry", () => {
  it("imports_compiled_tokens_css", () => {
    expect(main).toContain('import "@ei-ai/design-tokens/tokens.css"');
  });

  it("imports_self_hosted_ibm_plex_with_the_vietnamese_subset", () => {
    expect(main).toContain("@fontsource/ibm-plex-sans/latin-400.css");
    expect(main).toContain("@fontsource/ibm-plex-sans/vietnamese-400.css");
  });
});
