import test from "node:test";
import assert from "node:assert/strict";

import { formatNsat, transferRequirement, transferShortfall } from "./checkoutMath.js";

test("a transfer needs its amount, the network fee, and the two-reserve cushion", () => {
  assert.equal(transferRequirement({ amount: "1000", fee: 10, reserve: "100" }), 1210n);
  assert.equal(
    transferRequirement({ amount: "9223372036854775807", fee: 10, reserve: "100000000" }),
    9223372037054775817n,
  );
});

test("shortfall is exact and zero only when the balance covers the transfer", () => {
  assert.equal(transferShortfall({ amount: "1000", balance: "1210", fee: 10, reserve: "100" }), 0n);
  assert.equal(transferShortfall({ amount: "1000", balance: "1209", fee: 10, reserve: "100" }), 1n);
  assert.equal(
    transferShortfall({ amount: "9007199254740993", balance: "9007199254740993", fee: 10, reserve: "0" }),
    10n,
  );
});

test("invalid amounts are refused instead of becoming NaN", () => {
  assert.throws(() => transferRequirement({ amount: "1.5", fee: 10, reserve: "0" }), /checkout_amount_invalid/);
  assert.throws(() => transferRequirement({ amount: "", fee: 10, reserve: "0" }), /checkout_amount_invalid/);
  assert.throws(() => transferRequirement({ amount: "10", fee: -1, reserve: "0" }), /checkout_amount_invalid/);
  assert.throws(() => transferShortfall({ amount: "10", balance: "nope", fee: 10, reserve: "0" }), /checkout_balance_invalid/);
});

test("amounts print as grouped integers", () => {
  assert.equal(formatNsat("123456789"), "123,456,789");
  assert.equal(formatNsat(1000), "1,000");
  assert.equal(formatNsat("nope"), "—");
});
