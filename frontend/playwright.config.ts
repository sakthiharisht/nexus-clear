import { defineConfig } from "@playwright/test";

// Fixture/replay mode (SPEC.md section 14/M9 accept criterion): both
// servers run against the real committed model_cache - no
// ANTHROPIC_API_KEY needed, no live calls, fully offline and
// deterministic, same discipline as the backend's own pytest suite.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "uv run uvicorn app.main:app --port 8000",
      cwd: "../backend",
      url: "http://localhost:8000/health",
      reuseExistingServer: true,
      timeout: 30_000,
      env: { MODEL_CACHE_MODE: "replay" },
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: true,
      timeout: 30_000,
    },
  ],
});
