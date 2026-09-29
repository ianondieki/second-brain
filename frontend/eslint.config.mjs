import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // The web image excludes test/, e2e/ and *.test.* (.dockerignore) and `next build` type-checks everything left, so
  // app code must never import test helpers (a fixture under app/ importing @/test broke the image build).
  {
    files: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}", "i18n/**/*.{ts,tsx}"],
    ignores: ["**/*.test.ts", "**/*.test.tsx"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            { group: ["@/test", "@/test/*", "@/e2e", "@/e2e/*"], message: "Test helpers never ship: move this file under test/." },
            { group: ["vitest", "@testing-library/*", "@playwright/test"], message: "Test libraries never ship in app code." },
          ],
        },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
