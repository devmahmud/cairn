// Cairn frontend — ESLint flat config (BLUEPRINT.md §1, §8 step 8).

import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["dist", "coverage", "playwright-report", "test-results", "src/shared/types/api.ts"],
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs["recommended-latest"].rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    files: ["**/*.config.{ts,js}", "scripts/**/*.ts", "e2e/**/*.ts"],
    languageOptions: {
      globals: globals.node,
    },
  },
  {
    files: ["src/**/*.test.{ts,tsx}", "src/shared/lib/test-setup.ts"],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
);
