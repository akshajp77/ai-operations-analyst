import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * Vitest rather than Jest.
 *
 * It shares Vite's transform pipeline, so TypeScript, JSX, and path aliases
 * work with no extra Babel configuration, and the watch loop is fast enough
 * that engineers actually leave it running. Jest with Next.js needs a
 * transform layer that has to be kept in step with every framework upgrade.
 *
 * End-to-end tests are deliberately NOT here — a browser-driving runner
 * (Playwright) belongs in its own config so a slow suite can never creep into
 * the fast one.
 */
export default defineConfig({
  plugins: [react()],

  // Declaring PostCSS inline stops Vite from discovering postcss.config.mjs.
  // Tailwind v4's plugin cannot be loaded by Vite's CJS PostCSS resolver, and
  // unit tests assert on behaviour and accessible roles, never on computed
  // styles — so processing CSS here would only cost time and break the run.
  css: { postcss: { plugins: [] } },

  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],

    // Supplied explicitly rather than read from .env.local, so the suite is
    // hermetic: a developer's local configuration can never change what the
    // tests assert. `src/lib/env.ts` validates at module load and throws when
    // this is absent — which is the intended behaviour, not something to work
    // around.
    env: {
      NEXT_PUBLIC_API_BASE_URL: "http://api.test",
    },
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["node_modules", ".next", "e2e"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      // Exclude what a coverage number cannot say anything useful about:
      // generated code, type-only files, and vendored components.
      exclude: [
        "node_modules/",
        ".next/",
        "src/types/api.generated.ts",
        "src/components/ui/**",
        "**/*.d.ts",
        "**/*.config.*",
      ],
      thresholds: {
        // A floor, not a target. It exists to catch a pull request that adds
        // a feature and no tests; it is not a claim that 70% is good.
        lines: 70,
        functions: 70,
        branches: 70,
        statements: 70,
      },
    },
  },
  resolve: {
    // Must mirror the `paths` entry in tsconfig.json, or imports resolve in
    // the editor and fail in the test run.
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
