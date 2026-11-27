import { expect, test } from "@playwright/test";

test("Today keeps the shared bottom navigation available on phones", async ({ page }) => {
  await page.route("**/api/news/today/", (route) => route.fulfill({
    json: { items: [], global_available: true },
  }));
  await page.goto("/tests/fixtures/today-navigation.html");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  const today = nav.getByRole("button", { name: "Today", exact: true });
  const home = nav.getByRole("button", { name: "Home", exact: true });
  await today.click();
  const heading = page.getByRole("heading", { name: "Today", exact: true });
  await expect(heading).toBeVisible();
  await expect(today).toHaveAttribute("aria-current", "page");
  await expect(home).toBeInViewport({ ratio: 1 });

  const navBox = await nav.boundingBox();
  const headingBox = await heading.boundingBox();
  expect(navBox.y).toBeGreaterThan(headingBox.y + headingBox.height);
  await home.click();
  await expect(home).toHaveAttribute("aria-current", "page");
  await expect(heading).toHaveCount(0);

  // A full-screen conversation-style view still hides the main tabs.
  await page.getByRole("button", { name: "AI", exact: true }).click();
  await expect(nav).toBeHidden();
});
