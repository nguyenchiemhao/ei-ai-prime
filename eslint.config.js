// Flat ESLint config for the frontend workspaces (apps/*, packages/*). Scripts and docs checks are
// plain Node ESM covered by their own tests; Python is linted by ruff.
import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import prettier from "eslint-config-prettier";
import i18next from "eslint-plugin-i18next";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

const sources = ["apps/**/*.{ts,tsx}", "packages/**/*.{ts,tsx}"];

export default defineConfig(
  {
    ignores: [
      "**/dist/**",
      "**/node_modules/**",
      "**/coverage/**",
      "packages/api-types/src/schema.d.ts",
      "scripts/test-fixtures/**",
    ],
  },
  {
    files: sources,
    extends: [js.configs.recommended, tseslint.configs.recommended],
    languageOptions: { globals: { ...globals.browser } },
  },
  {
    // User-facing text goes through the message catalog (coding rule 7).
    files: sources,
    ignores: ["**/*.test.{ts,tsx}"],
    extends: [i18next.configs["flat/recommended"]],
    rules: {
      "i18next/no-literal-string": [
        "error",
        {
          // "jsx-only" also checks attributes (aria-label, title, placeholder, alt) and string
          // literals in JSX expressions. The exclude list keeps the plugin defaults and adds Preact's "class".
          mode: "jsx-only",
          "jsx-attributes": {
            exclude: ["className", "class", "styleName", "style", "type", "key", "id", "width", "height"],
          },
        },
      ],
    },
  },
  {
    // Playwright specs and config: Node code, no UI strings.
    files: ["e2e/**/*.ts", "playwright.config.ts"],
    extends: [js.configs.recommended, tseslint.configs.recommended],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    files: ["apps/admin/**/*.{ts,tsx}"],
    extends: [reactHooks.configs.flat.recommended],
  },
  {
    files: ["**/vite.config.ts"],
    languageOptions: { globals: { ...globals.node } },
  },
  prettier,
);
