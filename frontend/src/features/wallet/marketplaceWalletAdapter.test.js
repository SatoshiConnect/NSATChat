import test from "node:test";
import assert from "node:assert/strict";

import { createMarketplaceWalletAdapter } from "./marketplaceWalletAdapter.js";

test("wallet adapter defaults to read/sign/transfer disabled", async () => {
  const wallet = createMarketplaceWalletAdapter();
  assert.equal(wallet.canRead, false);
  assert.equal(wallet.canSign, false);
  assert.equal(wallet.canTransfer, false);
  await assert.rejects(wallet.readOnlyBalance("NSAT"), /not configured/i);
  await assert.rejects(wallet.requestSignature({ amount: "1" }), /signing is disabled/i);
});

test("wallet adapter exposes read-only balance through explicitly supplied functions", async () => {
  const wallet = createMarketplaceWalletAdapter({
    readAddress: async () => "GUSERADDRESS",
    readBalance: async ({ address, asset }) => `${address}:${asset}:12`,
  });
  assert.equal(wallet.canRead, true);
  assert.equal(wallet.canSign, false);
  assert.deepEqual(await wallet.readOnlyBalance("NSAT"), {
    address: "GUSERADDRESS",
    asset: "NSAT",
    balance: "GUSERADDRESS:NSAT:12",
  });
});
