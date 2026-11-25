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

test("uses a conservative reserve minimum only when the server omits live creation policy", async () => {
  const issue = await inspectCheckoutRecipients(order, async () => ({ destination_exists: false, base_reserve: "100000000" }));
  assert.deepEqual(issue, { role: "creator", amount: "10", minimum: "200000000", address: "Gcreator", self_open_available: false });
  assert.match(checkoutRecipientMessage(issue, "Creator share"), /10 NSAT/);
  assert.match(checkoutRecipientMessage(issue, "Creator share"), /live minimum of 200,000,000 NSAT/i);
  assert.match(checkoutRecipientMessage(issue, "Creator share"), /No payment has been sent/);
});

test("allows a 10 NSAT initial payment when Mainnet reports zero reserve for new accounts", async () => {
  const issue = await inspectCheckoutRecipients(order, async () => ({
    destination_exists: false,
    destination_creation_minimum: "0",
    account_reserve_floor: "0",
    zero_reserve_enabled: true,
    self_open_available: true,
  }));
  assert.equal(issue, null);
});

test("allows an initial payment that meets the live legacy reserve floor", async () => {
  const fundedOrder = { ...order, payments: [{ ...order.payments[0], amount_nsat: "200000000" }] };
  const issue = await inspectCheckoutRecipients(fundedOrder, async () => ({ destination_exists: false, base_reserve: "100000000" }));
  assert.equal(issue, null);
});

test("uses free owner activation guidance when it is enabled by policy", async () => {
  const issue = await inspectCheckoutRecipients(order, async () => ({
    destination_exists: false,
    destination_creation_minimum: "200000000",
    base_reserve: "100000000",
    self_open_available: true,
  }));
  assert.match(checkoutRecipientMessage(issue, "Creator share"), /open it for free/i);
});

test("refuses incomplete account existence state instead of guessing", async () => {
  await assert.rejects(
    inspectCheckoutRecipients(order, async () => ({ base_reserve: "100000000" })),
    /recipient_state_unknown/,
  );
});
