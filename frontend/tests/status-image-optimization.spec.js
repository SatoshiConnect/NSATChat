import { expect, test } from "@playwright/test";

for (const width of [4000, 1440]) {
  test(`handles standard and large Story photos (${width}px source)`, async ({ page }) => {
    await page.goto("/tests/fixtures/mobile-overflow.html");
    const result = await page.evaluate(async (sourceWidth) => {
      const { optimizeStatusImage } = await import("/src/utils/statusImageOptimization.js");
      const sourceCanvas = document.createElement("canvas");
      sourceCanvas.width = sourceWidth;
      sourceCanvas.height = Math.round(sourceWidth * 0.75);
      const context = sourceCanvas.getContext("2d");
      for (let y = 0; y < 30; y += 1) {
        for (let x = 0; x < 40; x += 1) {
          const hue = (x * 53 + y * 71) % 360;
          context.fillStyle = `hsl(${hue} 65% ${24 + ((x + y) % 45)}%)`;
          context.fillRect(x * sourceWidth / 40, y * sourceCanvas.height / 30, sourceWidth / 40 + 2, sourceCanvas.height / 30 + 2);
        }
      }
      const blob = await new Promise((resolve) => sourceCanvas.toBlob(resolve, "image/jpeg", 0.95));
      const original = new File([blob], "camera.jpg", { type: "image/jpeg" });
      const optimized = await optimizeStatusImage(original);
      const decoded = await createImageBitmap(optimized);
      const output = { originalBytes: original.size, optimizedBytes: optimized.size, width: decoded.width, height: decoded.height, type: optimized.type };
      decoded.close();
      return output;
    }, width);
    if (width > 1920) {
      expect(Math.max(result.width, result.height)).toBe(1920);
      expect(result.optimizedBytes).toBeLessThan(result.originalBytes);
    }
    else expect(Math.max(result.width, result.height)).toBe(width);
    expect(["image/jpeg", "image/webp", "image/png"]).toContain(result.type);
  });
}
