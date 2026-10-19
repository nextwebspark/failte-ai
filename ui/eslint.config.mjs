import { FlatCompat } from "@eslint/eslintrc";
import simpleImportSort from "eslint-plugin-simple-import-sort";
import unusedImports from "eslint-plugin-unused-imports";
import { dirname } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

// Colours come from the design tokens in globals.css (brand, ok, amber, sky,
// danger, live, ink, line, panel), which already switch for dark mode. A raw
// Tailwind palette class (text-red-500, bg-sky-50, …) bypasses them and needs
// its own dark: twin, so it is an error. See app-doc/claude-design/v3-audit.
const RAW_PALETTE_CLASS =
  "/(^|[\\s\"'`:!])(text|bg|border|border-[trblxyse]|ring|ring-offset|outline|divide|from|via|to|fill|stroke|placeholder|decoration|caret|accent|shadow)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-[0-9]{2,3}/";
const RAW_PALETTE_MESSAGE =
  "Use a design token (text-danger, bg-ok-dim, border-line, …) instead of a raw Tailwind palette colour.";

const eslintConfig = [
  // Ignore auto-generated hey-api client files
  { ignores: ["src/client/client/", "src/client/core/", "src/client/client.gen.ts", "src/client/sdk.gen.ts", "src/client/types.gen.ts", "src/client/index.ts"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    plugins: {
      "simple-import-sort": simpleImportSort,
      "unused-imports": unusedImports,
    },
    rules: {
      /* formatting / layout */
      "no-multiple-empty-lines": ["error", { max: 2, maxBOF: 1, maxEOF: 1 }],
      "eol-last": ["error", "always"],
      "no-trailing-spaces": "error",

      /* imports */
      "simple-import-sort/imports": "error",
      "simple-import-sort/exports": "error",
      "unused-imports/no-unused-imports": "error",
      "unused-imports/no-unused-vars": ["warn", { vars: "all", args: "after-used" }],

      /* design tokens */
      "no-restricted-syntax": [
        "error",
        { selector: `Literal[value=${RAW_PALETTE_CLASS}]`, message: RAW_PALETTE_MESSAGE },
        { selector: `TemplateElement[value.raw=${RAW_PALETTE_CLASS}]`, message: RAW_PALETTE_MESSAGE },
      ],
    },
    languageOptions: {
      sourceType: "module",
      ecmaVersion: "latest"
    }
  },
  {
    // The sign-in screens' brand panel is dark in both themes on purpose, and
    // tests may assert on raw classes.
    files: ["src/components/auth/**", "src/app/handler/**", "**/*.test.ts", "**/*.test.tsx"],
    rules: { "no-restricted-syntax": "off" },
  },
];

export default eslintConfig;
