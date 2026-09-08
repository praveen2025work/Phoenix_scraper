import { expect, test } from "@playwright/test";

test("create a capability, run it, see the board", async ({ page, request }) => {
  await request.post("http://localhost:8000/demo/seed");

  await page.goto("/");
  // API-key gate: submit blank (server runs open on localhost).
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByRole("button", { name: /new capability/i }).click();
  await page.getByLabel("id").fill("plex");
  await page.getByLabel("workflow stage").fill("plex");
  await page.getByRole("button", { name: /^create$/i }).click();

  await page.getByRole("link", { name: "plex" }).first().click();
  await expect(page.getByRole("heading", { name: /\/ plex/i })).toBeVisible();

  await page.getByRole("button", { name: /run now/i }).click();
  await expect(page.getByText(/in scope/i)).toBeVisible({ timeout: 20_000 });
});
