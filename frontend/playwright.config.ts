import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 45_000,
  fullyParallel: false,
  workers: 1,
  use: { baseURL: "http://localhost:5173", trace: "retain-on-failure" },
  webServer: [
    {
      command:
        "cd .. && uv run uvicorn --factory phoenix_scraper.api:create_app_default --port 8000 --host 127.0.0.1",
      port: 8000,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        PHEONIX_DB_PATH: "frontend/.e2e/e2e.db",
        PHEONIX_EXPORT_DIR: "frontend/.e2e/exports",
        PHEONIX_CAPABILITIES_DIR: "frontend/.e2e/caps",
        PHEONIX_CORS_ORIGINS: "http://localhost:5173",
      },
    },
    {
      command: "npm run dev",
      port: 5173,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
