import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createWalletRequestMessage, parseWalletRequestMessage } from "./paymentRequest.js";

const ADDRESS = `G${"A".repeat(55)}`;

describe("in-chat NSAT payment requests", () => {
  it("round-trips a request with an exact whole-unit amount", () => {
    const message = createWalletRequestMessage({ address: ADDRESS, amount: "123456789" });
    assert.deepEqual(parseWalletRequestMessage(message), { address: ADDRESS, amount: "123456789" });
  });

  it("round-trips an amount-free request", () => {
    const message = createWalletRequestMessage({ address: ADDRESS });
    assert.deepEqual(parseWalletRequestMessage(message), { address: ADDRESS, amount: "" });
  });

  it("rejects malformed addresses, amounts, versions, and payloads", () => {
    assert.throws(() => createWalletRequestMessage({ address: "not-an-address" }), /invalid_wallet_address/);
    assert.throws(() => createWalletRequestMessage({ address: ADDRESS, amount: "0" }), /invalid_wallet_amount/);
    assert.equal(parseWalletRequestMessage("ordinary chat text"), null);
    assert.equal(parseWalletRequestMessage("__SATOSHICORE_WALLET_REQUEST_V1__:{bad json"), null);
    assert.equal(parseWalletRequestMessage(`__SATOSHICORE_WALLET_REQUEST_V1__:{"v":2,"address":"${ADDRESS}"}`), null);
  });
});
