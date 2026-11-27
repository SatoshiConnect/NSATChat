import { expect, test } from "@playwright/test";

test("a comment invalidation patches only its post without reloading", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("access_token", "fixture-token"));
  let socket;
  let watched;
  let frames = 0;
  let changed = false;
  await page.routeWebSocket(/\/ws\/chat\/inbox\//, (connection) => {
    socket = connection;
    connection.onMessage((text) => {
      const data = JSON.parse(text);
      if (data.type === "social.watch" && data.post_ids.length) {
        watched = data.post_ids;
        connection.send(JSON.stringify({ type: "social.watching", post_ids: watched }));
      }
    });
  });
  await page.route(/\/api\/social\/posts\/interactions\//, (route) => {
    const ids = new URL(route.request().url()).searchParams.get("ids").split(",");
    return route.fulfill({ json: ids.map(Number).map((id) => ({
      id,
      comments_count: changed && id === 41 ? 1 : 0,
      comments: changed && id === 41 ? [{ id: 1, text: "Comment from another account" }] : [],
    })) });
  });
  page.on("framenavigated", (frame) => { if (frame === page.mainFrame()) frames += 1; });
  await page.goto("/tests/fixtures/social-interactions.html");
  await expect.poll(() => watched).toEqual([41, 42]);
  const post = page.getByRole("region", { name: "Post 41" });
  await expect(post).toContainText("0 comments");
  await expect(page.getByText("Comment from another account")).toHaveCount(0);
  changed = true;
  socket.send(JSON.stringify({ type: "social.interaction_changed", post_id: 41 }));
  await expect(post).toContainText("Comment from another account");
  await expect(post).toContainText("1 comments");
  await expect(page.getByRole("region", { name: "Post 42" })).toContainText("0 comments");
  expect(frames).toBe(1);
});
