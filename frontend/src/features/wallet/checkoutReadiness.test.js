import test from "node:test";
import assert from "node:assert/strict";
import { checkoutRecipientMessage, inspectCheckoutRecipients } from "./checkoutReadiness.js";

const order = {
  buyer_address: "Gbuyer",
  payments: [{ role: "creator", payee_address: "Gcreator", amount_nsat: "10", state: "pending" }],
};

test("does not block an existing recipient regardless of listing price", async () => {
  const issue = await inspectCheckoutRecipients(order, async () => ({ destination_exists: true, base_reserve: "100000000" }));
  assert.equal(issue, null);
});

test("blocks an unactivated payee when the listed amount is below the current account-creation floor", async () => {
  const issue = await inspectCheckoutRecipients(order, async () => ({ destination_exists: false, base_reserve: "100000000" }));
  assert.deepEqual(issue, { role: "creator", amount: "10", minimum: "200000000" });
  assert.match(checkoutRecipientMessage(issue, "Creator share"), /10 NSAT/);
  assert.match(checkoutRecipientMessage(issue, "Creator share"), /200,000,000 NSAT/);
  assert.match(checkoutRecipientMessage(issue, "Creator share"), /No payment has been sent/);
});

test("allows an initial payment that meets the live reserve floor", async () => {
  const fundedOrder = { ...order, payments: [{ ...order.payments[0], amount_nsat: "200000000" }] };
  const issue = await inspectCheckoutRecipients(fundedOrder, async () => ({ destination_exists: false, base_reserve: "100000000" }));
  assert.equal(issue, null);
});

test("refuses incomplete account state instead of guessing", async () => {
  await assert.rejects(
    inspectCheckoutRecipients(order, async () => ({ destination_exists: false })),
    /recipient_state_unknown/,
  );
});
