import js from "@eslint/js";
import ts from "typescript-eslint";

const source = ["src/**/*.{ts,tsx}"];
export default ts.config(
  { ignores: ["src/contracts/generated.ts", "**/*.test.*", "**/*.spec.*"] },
  { ...js.configs.recommended, files: source },
  ...ts.configs.recommended.map((config) => ({ ...config, files: source })),
  {
    files: source,
    rules: {
      // Mutable legacy form dictionaries are being narrowed at feature boundaries.
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
      "no-undef": "off",
      "no-empty": ["error", { allowEmptyCatch: true }],
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/App", "**/App.tsx"],
              caseSensitive: true,
              message:
                "Features must not import the application shell. Pass a typed callback instead.",
            },
          ],
        },
      ],
    },
  },
  {
    files: [
      "src/lib/**/*.{ts,tsx}",
      "src/contracts/**/*.{ts,tsx}",
      "src/services/**/*.{ts,tsx}",
      "src/components/**/*.{ts,tsx}",
    ],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/features/**", "**/app/**", "**/App*"],
              caseSensitive: true,
              message:
                "Shared layers must not depend on application orchestration or features.",
            },
          ],
        },
      ],
    },
  },
);
