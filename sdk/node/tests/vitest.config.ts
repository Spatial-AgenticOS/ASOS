// Vitest configuration scoped to `sdk/node/tests/`. The package itself
// does not commit a top-level vitest config (W10 owns `tests/**` only —
// see docs/AGENT_PROMPTS.md §C.2), so we keep the config under the test
// directory and point the workflow at it explicitly via `--config`.
//
// The `tsconfig.json` in `sdk/node/` already targets `dist/`, so we add
// the `src/` path here for the test resolver. Once the SDK owners commit
// a top-level vitest config and a `test` script in `package.json`, this
// file can be retired.

import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

export default defineConfig({
  resolve: {
    alias: {
      "@feral/sdk": resolve(__dirname, "../src/index.ts"),
    },
  },
  test: {
    include: ["**/*.test.ts"],
    environment: "node",
    globals: false,
    reporters: "default",
  },
});
