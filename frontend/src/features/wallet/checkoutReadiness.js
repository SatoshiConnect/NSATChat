import { formatNsat } from "./checkoutMath.js";

/** Check every unpaid payee before asking the buyer to unlock or sign. */
export async function inspectCheckoutRecipients(order, readPreflight) {
  const pending = (order?.payments || []).filter((payment) => payment.state !== "confirmed");
  for (const payment of pending) {
    const facts = await readPreflight(order.buyer_address, payment.payee_address);
    if (typeof facts.destination_exists !== "boolean") throw new Error("recipient_state_unknown");
    if (facts.destination_exists) continue;

    let amount;
    let reserve;
    try {
      amount = BigInt(payment.amount_nsat);
      reserve = BigInt(facts.base_reserve);
    } catch {
      throw new Error("recipient_state_unknown");
    }
    if (amount < 0n || reserve < 0n) throw new Error("recipient_state_unknown");
    const minimum = reserve * 2n;
    if (amount < minimum) {
      return {
        role: payment.role,
        amount: amount.toString(),
        minimum: minimum.toString(),
      };
    }
  }
  return null;
}

export function checkoutRecipientMessage(issue, roleLabel = "Recipient") {
  return `${roleLabel} wallet is not activated on NSAT Mainnet. This item is priced at ${formatNsat(issue.amount)} NSAT, but a new recipient account requires a first payment of at least ${formatNsat(issue.minimum)} NSAT under the current reserve rule. The seller must activate the wallet before this item can be purchased. No payment has been sent.`;
}
