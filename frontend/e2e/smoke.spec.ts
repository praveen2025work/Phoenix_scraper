import { expect, test } from "@playwright/test";

const API = "http://localhost:8000";

test("create a capability, run it, see the board", async ({ page, request }) => {
  await request.post(`${API}/demo/seed`);
  // idempotent setup: start from a clean 'plex' capability.
  await request.delete(`${API}/capabilities/plex?purge=true`);

  await page.goto("/");
  // API-key gate: submit blank (server runs open on localhost).
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByRole("button", { name: /new capability/i }).click();
  await page.getByLabel("id").fill("plex");
  await page.getByLabel("workflow stage").fill("plex");
  await page.getByRole("button", { name: /^create$/i }).click();

  await page.getByRole("link", { name: "plex" }).first().click();
  await expect(page.getByRole("heading", { name: /\/ plex/i })).toBeVisible();
  await expect(page.getByText("No runs yet.")).toBeVisible();

  await page.getByRole("button", { name: /run now/i }).click();
  // the run is enqueued as a background job; the button re-enables once the
  // worker finishes it and the SPA's poll settles.
  await expect(page.getByRole("button", { name: /^run now$/i })).toBeEnabled({
    timeout: 30_000,
  });
  // the run-summary panel replaces "No runs yet." once the run lands
  await expect(page.getByText("No runs yet.")).toBeHidden({ timeout: 30_000 });
  await expect(page.getByText(/in scope/i)).toBeVisible();
});
