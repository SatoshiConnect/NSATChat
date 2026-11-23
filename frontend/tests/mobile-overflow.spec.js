import { test, expect } from "@playwright/test";

const widths = [320, 375, 390, 430];
const modes = ["chat", "group", "ai"];

async function measure(page) {
  return page.evaluate(() => {
    const selectors = [
      ".app", ".conversation.is-active", ".messages", ".msg-row", ".bubble--out", ".contact-card", ".status-reaction", ".audio",
      ".composer", ".composer__row", ".composer__pill", ".composer__input", ".composer__mic", ".composer__action",
    ];
    const elements = selectors.flatMap((selector) => [...document.querySelectorAll(selector)].slice(-1).map((element) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return { selector, rect: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height }, fontSize: style.fontSize };
    }));
    return {
      viewport: {
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        visualWidth: visualViewport?.width ?? null,
        visualHeight: visualViewport?.height ?? null,
        scale: visualViewport?.scale ?? null,
        offsetLeft: visualViewport?.offsetLeft ?? null,
        offsetTop: visualViewport?.offsetTop ?? null,
        scrollX: window.scrollX,
        scrollY: window.scrollY,
      },
      elements,
    };
  });
}

async function assertNoDocumentOverflow(page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
}

async function assertVisibleBounds(page, selector, viewportWidth) {
  const boxes = await page.locator(selector).evaluateAll((elements) => elements
    .filter((element) => !element.hidden && getComputedStyle(element).display !== "none")
    .map((element) => {
      const rect = element.getBoundingClientRect();
      return { left: rect.left, right: rect.right, width: rect.width };
    }));
  expect(boxes.length, `${selector} should be rendered`).toBeGreaterThan(0);
  for (const box of boxes) {
    expect(box.width, `${selector} should have a layout box`).toBeGreaterThan(0);
    expect(box.left, `${selector} left edge ${box.left} should be inside ${viewportWidth}px viewport`).toBeGreaterThanOrEqual(-0.5);
    expect(box.right, `${selector} right edge ${box.right} should be inside ${viewportWidth}px viewport`).toBeLessThanOrEqual(viewportWidth + 0.5);
  }
}

for (const width of widths) {
  for (const mode of modes) {
    test(`${mode} focus, typing, send, blur and orientation fit ${width}px`, async ({ page }, testInfo) => {
      const diagnosticHandles = [];
      page.on("console", (message) => {
        if (!message.text().startsWith("[mhtalk-viewport-diagnostic]")) return;
        const objectHandle = message.args()[1];
        if (objectHandle) diagnosticHandles.push(objectHandle);
      });

      await page.setViewportSize({ width, height: 844 });
      await page.goto(`/tests/fixtures/mobile-overflow.html?mode=${mode}`);
      await page.locator(".conversation.is-active").waitFor();
      expect(await page.evaluate(() => matchMedia("(hover: none) and (pointer: coarse)").matches)).toBe(true);
      const checkpoints = { initial: await measure(page) };
      const captureViewportEvidence = width === 390 && mode === "chat" && testInfo.project.name === "ios-webkit";
      if (captureViewportEvidence) {
        const screenshot = await page.screenshot({ path: testInfo.outputPath("ios-webkit-before-keyboard-like-resize.png") });
        await testInfo.attach("ios-webkit-before-keyboard-like-resize.png", {
          body: screenshot,
          contentType: "image/png",
        });
      }
      const baselineOverride = await page.addStyleTag({ content: `
        @media (max-width: 900px) {
          .status-reaction { min-width: 240px; width: auto; max-width: 330px; }
          .contact-card { min-width: 250px; width: auto; max-width: 100%; margin: -2px -3px 4px; }
          .audio { width: 240px; max-width: none; }
          .app .composer__input { font-size: 15px !important; }
        }
      ` });
      checkpoints.previousRulesSimulation = await measure(page);
      await baselineOverride.evaluate((style) => style.remove());
      checkpoints.fixedRules = await measure(page);
      const simulatedInputFont = parseFloat(checkpoints.previousRulesSimulation.elements.find((element) => element.selector === ".composer__input")?.fontSize);
      expect(simulatedInputFont).toBe(15);
      expect(checkpoints.initial.viewport.innerWidth).toBe(width);
      await assertNoDocumentOverflow(page);
      await assertVisibleBounds(page, ".conversation.is-active", width);
      await assertVisibleBounds(page, ".conversation.is-active .bubble", width);
      await assertVisibleBounds(page, ".conversation.is-active .bubble__text", width);
      if (mode !== "ai") {
        await assertVisibleBounds(page, ".conversation.is-active .contact-card", width);
        await assertVisibleBounds(page, ".conversation.is-active .status-reaction", width);
        await assertVisibleBounds(page, ".conversation.is-active .audio", width);
      }
      await assertVisibleBounds(page, ".conversation.is-active .composer", width);
      await assertVisibleBounds(page, ".conversation.is-active .composer__pill", width);

      const input = page.locator(".conversation.is-active textarea");
      const initialInputFont = parseFloat(await input.evaluate((element) => getComputedStyle(element).fontSize));
      expect(initialInputFont).toBeGreaterThanOrEqual(16);
      const previousInputFont = parseFloat(await page.locator(".mobile-input-audit .composer__input").evaluate((element) => getComputedStyle(element).fontSize));
      expect(previousInputFont).toBeGreaterThanOrEqual(16);
      const mobileTextControlFonts = await page.locator(".mobile-input-audit input, .mobile-input-audit textarea, .mobile-input-audit select, .mobile-input-audit [contenteditable='true']").evaluateAll((elements) => elements.map((element) => parseFloat(getComputedStyle(element).fontSize)));
      expect(mobileTextControlFonts.every((fontSize) => fontSize >= 16)).toBe(true);
      await input.click();
      checkpoints.focus = await measure(page);
      const longMessage = `${"ข้อความไทยไม่มีช่องว่าง".repeat(12)} https://example.invalid/very/long/path/which/must/wrap/inside/the/message/bubble`;
      await input.fill(longMessage);
      checkpoints.typing = await measure(page);
      await assertNoDocumentOverflow(page);
      await assertVisibleBounds(page, ".conversation.is-active .composer", width);
      if (mode === "ai") {
        await assertVisibleBounds(page, '.conversation.is-active button[aria-label="Send to SatoshiCore AI"]', width);
        await input.press("Enter");
      } else {
        await assertVisibleBounds(page, '.conversation.is-active button[aria-label="Send"]', width);
        await assertVisibleBounds(page, '.conversation.is-active button[aria-label="Attach"], .conversation.is-active button[aria-label="Camera"]', width);
        await page.locator('.conversation.is-active button[aria-label="Send"]').click();
      }
      checkpoints.sent = await measure(page);
      await assertNoDocumentOverflow(page);
      await assertVisibleBounds(page, ".conversation.is-active .bubble", width);
      if (mode !== "ai") await assertVisibleBounds(page, '.conversation.is-active button[aria-label="Microphone"]', width);

      // Resizing the viewport height is keyboard-like only; it is not native iOS keyboard emulation.
      const messageList = page.locator(".conversation.is-active .messages");
      await messageList.evaluate((node) => {
        const inner = node.firstElementChild;
        for (let index = 0; index < 24; index += 1) {
          const row = document.createElement("div");
          row.className = "msg-row msg-row--in";
          row.innerHTML = '<div class="msg-row__inner"><div class="bubble bubble--in"><span class="bubble__text"></span></div></div>';
          row.querySelector(".bubble__text").textContent = `older message ${index}`;
          inner.append(row);
        }
        node.scrollTop = node.scrollHeight;
      });
      await input.focus();
      await page.setViewportSize({ width, height: 480 });
      await page.waitForTimeout(375);
      checkpoints.keyboardLikeResize = await measure(page);
      if (captureViewportEvidence) {
        const screenshot = await page.screenshot({ path: testInfo.outputPath("ios-webkit-after-keyboard-like-resize.png") });
        await testInfo.attach("ios-webkit-after-keyboard-like-resize.png", {
          body: screenshot,
          contentType: "image/png",
        });
      }
      await assertNoDocumentOverflow(page);
      await assertVisibleBounds(page, ".conversation.is-active .composer", width);
      await assertVisibleBounds(page, ".conversation.is-active .composer__action", width);
      const bottomGap = await messageList.evaluate((node) => node.scrollHeight - node.scrollTop - node.clientHeight);
      expect(bottomGap).toBeLessThanOrEqual(1);

      // A user who has scrolled back should keep their reading position while
      // the visible viewport changes again.
      await messageList.evaluate((node) => { node.scrollTop = 0; });
      await page.setViewportSize({ width, height: 430 });
      await page.waitForTimeout(375);
      expect(await messageList.evaluate((node) => node.scrollTop)).toBeLessThanOrEqual(1);

      await input.evaluate((element) => element.blur());
      await page.waitForTimeout(375);
      checkpoints.blur = await measure(page);
      await page.setViewportSize({ width, height: 844 });
      await assertNoDocumentOverflow(page);
      await assertVisibleBounds(page, ".conversation.is-active .composer", width);
      for (let attempt = 0; attempt < 2; attempt += 1) {
        await input.focus();
        await input.evaluate((element) => element.blur());
      }
      checkpoints.repeatedFocusBlur = await measure(page);

      // Rotate while the room remains mounted, then return to portrait.
      await input.focus();
      await page.setViewportSize({ width: 844, height: 390 });
      await page.waitForFunction(() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--app-viewport-height")) === 390);
      checkpoints.landscape = await measure(page);
      await assertNoDocumentOverflow(page);
      await assertVisibleBounds(page, ".conversation.is-active .composer", 844);
      await assertVisibleBounds(page, ".conversation.is-active .composer__action", 844);
      await page.setViewportSize({ width: 956, height: 430 });
      await page.waitForFunction(() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--app-viewport-height")) === 430);
      checkpoints.wideLandscape = await measure(page);
      await assertNoDocumentOverflow(page);
      await assertVisibleBounds(page, ".conversation.is-active .composer", 956);
      await page.setViewportSize({ width, height: 844 });
      await page.waitForFunction(() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--app-viewport-height")) === 844);
      checkpoints.returnToPortrait = await measure(page);
      await assertNoDocumentOverflow(page);
      await assertVisibleBounds(page, ".conversation.is-active .bubble", width);

      const diagnostics = await Promise.all(diagnosticHandles.map((handle) => handle.jsonValue()));
      expect(diagnostics.some((entry) => entry.phase === "initial")).toBe(true);
      expect(diagnostics.some((entry) => entry.phase === "before-focus")).toBe(true);
      expect(diagnostics.some((entry) => entry.phase === "focus")).toBe(true);
      expect(diagnostics.some((entry) => entry.phase === "blur")).toBe(true);
      expect(diagnostics.some((entry) => entry.phase === "visual-viewport-resize" || entry.phase === "window-resize")).toBe(true);
      expect(diagnostics.some((entry) => entry.phase.startsWith("after-keyboard-open"))).toBe(true);
      expect(JSON.stringify(diagnostics).includes(longMessage)).toBe(false);
      await testInfo.attach(`viewport-${mode}-${width}.json`, {
        body: new TextEncoder().encode(JSON.stringify({ checkpoints, diagnostics: diagnostics.map(({ phase, viewport, overflow }) => ({ phase, viewport, overflow })) }, null, 2)),
        contentType: "application/json",
      });
    });
  }
}
