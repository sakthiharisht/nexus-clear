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
  // Both servers addressed as the literal IP 127.0.0.1, not the hostname
  // "localhost", and consistently so on both sides (page origin and API
  // target). Two real, separate failure modes otherwise: (1) uvicorn
  // binds IPv4-only by default, Vite binds dual-stack, so a browser
  // whose Happy Eyeballs picks ::1 for "localhost:8000" gets a silent
  // connection failure with nothing in the backend's log; (2) if only
  // the API target is pinned to the IP literal while the page origin
  // stays on the hostname "localhost", Chrome's Private Network Access
  // check sees that as a transition into a more-private address space
  // and requires a preflight opt-in Starlette's CORSMiddleware has no
  // constructor option for, so it 400s with "Disallowed CORS
  // private-network" - confirmed directly against the running backend.
  // Real usage (docker compose) never hits either: the built frontend
  // and the API are both reached via the same hostname there.
  use: {
    baseURL: "http://127.0.0.1:5173",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "uv run uvicorn app.main:app --port 8000",
      cwd: "../backend",
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: true,
      timeout: 30_000,
      env: { MODEL_CACHE_MODE: "replay" },
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: true,
      timeout: 30_000,
      env: { VITE_API_BASE_URL: "http://127.0.0.1:8000" },
    },
  ],
});
