import { expect, test } from "@playwright/test";

const NETWORK = "NSAT Mainnet ; October 2026 ; bc3098829fffc717";
const fixture = "/tests/fixtures/wallet-activation.html";

async function mountWallet(page, { submit, confirm }) {
  let active = false;
  let submissions = 0;
  const receipts = [];
  // All wallet requests stay on localhost and are intercepted. No request reaches a real backend.
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const url = new URL(route.request().url());
    const address = url.searchParams.get("address");
    const reply = (json) => route.fulfill({ json });
    switch (url.pathname) {
      case "/api/wallet/link/me/": return reply({ connected: false });
      case "/api/wallet/read/": return reply({
        address, network: NETWORK, history: [], balance: "0", account_status: active ? "active" : "not_found",
      });
      case "/api/wallet/self-open/preflight/": return reply({
        address, network: NETWORK, account_exists: false, available: true, protocol_version: 16,
      });
      case "/api/wallet/submit/":
        submissions += 1;
        return submit(route, reply);
      default: {
        const match = url.pathname.match(/^\/api\/wallet\/confirmation\/([a-f0-9]{64})\/$/);
        if (!match) return route.abort();
        const hash = match[1];
        receipts.push({ hash, submittedAt: url.searchParams.get("submitted_at") });
        const verdict = await confirm(receipts.length);
        active = verdict.status === "confirmed" && verdict.success === true;
        return reply({ hash, ...verdict });
      }
    }
  });
  await page.goto(fixture);
  await page.getByRole("button", { name: "Unlock to activate free" }).click();
  await page.getByLabel("Device password").fill("fixture-password");
  await page.locator(".wallet-native__inline-unlock").getByRole("button", { name: "Unlock", exact: true }).click();
  await page.getByRole("button", { name: "Activate wallet for free" }).click();
  const dialog = page.getByRole("dialog", { name: "Review free wallet activation" });
  await dialog.getByRole("button", { name: "Open wallet for free" }).click();
  return { submissions: () => submissions, receipts: () => receipts };
}

test("recovers the same activation after a relay network error and reload", async ({ page }) => {
  const tracker = await mountWallet(page, {
    submit: (route) => route.abort("failed"),
    confirm: (attempt) => attempt === 1 ? { status: "not_found" } : { status: "confirmed", success: true, ledger: 123 },
  });
  const status = page.getByRole("status", { name: "Wallet activation status" });
  await expect(status).toContainText("Activation status unknown");
  const hash = await status.locator("code").textContent();
  expect(hash).toMatch(/^[a-f0-9]{64}$/);
  await expect(page.getByRole("button", { name: "Activate wallet for free" })).toBeDisabled();
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(status).toContainText(hash);

  await page.reload();
  await expect(status).toContainText(hash);
  await expect(page.getByRole("button", { name: "Unlock to activate free" })).toBeDisabled();
  await status.getByRole("button", { name: "Check status", exact: true }).click();
  await expect(status).toContainText("Activation status unknown");
  await status.getByRole("button", { name: "Check status", exact: true }).click();
  await expect(status).toContainText("Wallet opened on Mainnet");
  await expect(status).toContainText("Ledger #123");
  await expect(page.getByRole("region", { name: "Free wallet activation" })).toHaveCount(0);
  const receipts = tracker.receipts();
  expect(receipts).toHaveLength(2);
  expect(receipts[0]).toEqual({ hash, submittedAt: expect.stringMatching(/^\d+$/) });
  expect(receipts[1]).toEqual(receipts[0]);
  expect(tracker.submissions()).toBe(1);
});

test("shows pending status during automatic polling and unblocks after a verified rejection", async ({ page }) => {
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const tracker = await mountWallet(page, {
    submit: (_route, reply) => reply({ status: "PENDING" }),
    confirm: (attempt) => attempt === 1 ? pending : { status: "failed", success: false, result_code: "tx_failed" },
  });
  const status = page.getByRole("status", { name: "Wallet activation status" });
  await expect(status).toContainText("Opening wallet on Mainnet");
  await expect(status.getByRole("button", { name: "Checking status…" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Activate wallet for free" })).toBeDisabled();
  release({ status: "not_found" });
  await expect(status).toContainText("Activation status unknown");
  await status.getByRole("button", { name: "Check status", exact: true }).click();
  await expect(status).toContainText("Wallet activation failed");
  await expect(page.getByRole("button", { name: "Activate wallet for free" })).toBeEnabled();
  expect(tracker.receipts()).toHaveLength(2);
  expect(tracker.receipts()[1]).toEqual(tracker.receipts()[0]);
  expect(tracker.submissions()).toBe(1);
});

test("does not relay an activation if the recovery reference cannot be saved", async ({ page }) => {
  await page.addInitScript(() => {
    const setItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith("satoshicore:messenger-self-open:v1:")) {
        throw new DOMException("Storage denied", "QuotaExceededError");
      }
      return setItem.call(this, key, value);
    };
  });
  const tracker = await mountWallet(page, {
    submit: (route) => route.abort("failed"),
    confirm: () => ({ status: "not_found" }),
  });
  await expect(page.getByRole("alert")).toContainText("Nothing was submitted.");
  expect(tracker.submissions()).toBe(0);
  expect(tracker.receipts()).toHaveLength(0);
});
