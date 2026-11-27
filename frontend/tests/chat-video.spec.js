import { Buffer } from "node:buffer";
import { expect, test } from "@playwright/test";
import { tinyMp4Base64 } from "./fixtures/synthetic-video";

const mp4 = Buffer.from(tinyMp4Base64, "base64");

async function respondWithVideo(route) {
  const range = /^bytes=(\d+)-(\d*)$/.exec(route.request().headers().range || "");
  if (!range) return route.fulfill({ body: mp4, contentType: "video/mp4", headers: { "accept-ranges": "bytes" } });
  const start = Number(range[1]);
  const end = Math.min(range[2] ? Number(range[2]) : mp4.length - 1, mp4.length - 1);
  const contentRange = start <= end ? `bytes ${start}-${end}/${mp4.length}` : `bytes */${mp4.length}`;
  return route.fulfill({
    status: start <= end ? 206 : 416,
    contentType: "video/mp4",
    headers: { "content-range": contentRange, "accept-ranges": "bytes" },
    body: start <= end ? mp4.subarray(start, end + 1) : Buffer.alloc(0),
  });
}

test("offers retry and original download when the selected chat video fails", async ({ page }) => {
  let available = false;
  await page.route("**/qa-video/*.mp4", (route) => available
    ? respondWithVideo(route)
    : route.fulfill({ status: 503, headers: { "cache-control": "no-store" } }));
  await page.goto("/tests/fixtures/chat-video.html");
  await page.getByRole("button", { name: "Play received attachment" }).click();
  const player = page.getByRole("dialog", { name: "Media viewer" });
  const alert = player.getByRole("alert");
  await expect(alert).toContainText("This video couldn’t be played.");
  await expect(alert.getByRole("link", { name: "Download original" })).toHaveAttribute("href", /\/qa-video\/one\.mp4$/);
  available = true;
  await alert.getByRole("button", { name: "Try again" }).click();
  await expect(alert).toHaveCount(0);
  const video = player.locator(".lightbox__stage video");
  await expect.poll(() => video.evaluate((el) => el.videoWidth)).toBe(32);
});

test("does not carry a playback failure to the next attachment", async ({ page }) => {
  await page.route("**/qa-video/*.mp4", (route) => route.request().url().endsWith("/one.mp4")
    ? route.fulfill({ status: 404 })
    : respondWithVideo(route));
  await page.goto("/tests/fixtures/chat-video.html");
  await page.getByRole("button", { name: "Play received attachment" }).click();
  const player = page.getByRole("dialog", { name: "Media viewer" });
  await expect(player.getByRole("alert")).toBeVisible();
  await player.getByRole("button", { name: "Next", exact: true }).click();
  await expect(player.getByRole("alert")).toHaveCount(0);
  await expect.poll(() => player.locator(".lightbox__stage video").evaluate((el) => el.videoWidth)).toBe(32);
});
