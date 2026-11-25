import { formatNsat } from "./checkoutMath.js";

/** Check every unpaid payee before asking the buyer to unlock or sign. */
export async function inspectCheckoutRecipients(order, readPreflight) {
  const pending = (order?.payments || []).filter((payment) => payment.state !== "confirmed");
  for (const payment of pending) {
    const facts = await readPreflight(order.buyer_address, payment.payee_address);
    if (typeof facts.destination_exists !== "boolean") throw new Error("recipient_state_unknown");
    if (facts.destination_exists) continue;

    let amount;
    let minimum;
    try {
      amount = BigInt(payment.amount_nsat);
      minimum = facts.destination_creation_minimum == null
        ? BigInt(facts.base_reserve) * 2n
        : BigInt(facts.destination_creation_minimum);
    } catch {
      throw new Error("recipient_state_unknown");
    }
    if (amount < 0n || minimum < 0n) throw new Error("recipient_state_unknown");
    if (amount < minimum) {
      return {
        role: payment.role,
        amount: amount.toString(),
        minimum: minimum.toString(),
        address: payment.payee_address,
        self_open_available: facts.self_open_available === true,
      };
    }
  }
  return null;
}

export function checkoutRecipientMessage(issue, roleLabel = "Recipient") {
  const nextStep = issue.self_open_available
    ? "The wallet owner can open it for free from Wallet using the wallet's own key."
    : `The wallet owner must activate it or the first payment must meet the live minimum of ${formatNsat(issue.minimum)} NSAT.`;
  return `${roleLabel} wallet has not been opened on NSAT Mainnet. ${nextStep} The listed ${formatNsat(issue.amount)} NSAT price remains unchanged. No payment has been sent.`;
}
