import { test, expect } from "@playwright/test";

const widths = [320, 360, 375, 390, 393, 430];

async function assertVisibleBounds(page, selector, viewportWidth) {
  const boxes = await page.locator(selector).evaluateAll((elements) => elements.map((element) => {
    const rect = element.getBoundingClientRect();
    return { left: rect.left, right: rect.right, width: rect.width };
  }));
  for (const box of boxes) {
    expect(box.width, `${selector} should have a layout box`).toBeGreaterThan(0);
    expect(box.left, `${selector} left edge ${box.left} should be inside ${viewportWidth}px viewport`).toBeGreaterThanOrEqual(-0.5);
    expect(box.right, `${selector} right edge ${box.right} should be inside ${viewportWidth}px viewport`).toBeLessThanOrEqual(viewportWidth + 0.5);
  }
}

async function assertNoDocumentOverflow(page) {
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
}

for (const width of widths) {
  for (const mode of ["chat", "ai"]) {
    test(`${mode} layout fits ${width}px viewport and keyboard-like resize`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(`/tests/fixtures/mobile-overflow.html?mode=${mode}`);
      await page.locator(".conversation.is-active").waitFor();

      const innerWidth = await page.evaluate(() => window.innerWidth);
      await assertNoDocumentOverflow(page);
      expect(innerWidth).toBe(width);
      await assertVisibleBounds(page, ".conversation.is-active", width);
      await assertVisibleBounds(page, ".conversation.is-active .bubble", width);
      await assertVisibleBounds(page, ".conversation.is-active .bubble__text", width);
      await assertVisibleBounds(page, ".conversation.is-active .contact-card", width);
      await assertVisibleBounds(page, ".conversation.is-active .status-reaction", width);
      await assertVisibleBounds(page, ".conversation.is-active .audio", width);
      await assertVisibleBounds(page, ".conversation.is-active .composer", width);
      await assertVisibleBounds(page, ".conversation.is-active .composer__action", width);
      if (mode === "chat") {
        await assertVisibleBounds(page, '.conversation.is-active button[aria-label="Microphone"]', width);
        await page.locator("#chat-input").fill("sent message");
        await assertVisibleBounds(page, '.conversation.is-active button[aria-label="Send"]', width);
        await assertVisibleBounds(page, '.conversation.is-active button[aria-label="Attach"], .conversation.is-active button[aria-label="Camera"]', width);
      } else {
        await assertVisibleBounds(page, '.conversation.is-active button[aria-label="Send to SatoshiCore AI"]', width);
        await assertVisibleBounds(page, '.conversation.is-active button[aria-label="Paste"], .conversation.is-active button[aria-label="Photo"], .conversation.is-active button[aria-label="Camera"]', width);
      }

      await page.locator(".conversation.is-active textarea").focus();
      await page.setViewportSize({ width, height: 480 });
      await assertNoDocumentOverflow(page);
      await assertVisibleBounds(page, ".conversation.is-active .composer", width);
      await assertVisibleBounds(page, ".conversation.is-active .composer__action", width);
      await page.setViewportSize({ width, height: 844 });
      await assertNoDocumentOverflow(page);
      await assertVisibleBounds(page, ".conversation.is-active .composer", width);
    });
  }
}
