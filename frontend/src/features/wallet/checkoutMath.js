/**
 * Exact checkout arithmetic for a single NSAT transfer.
 *
 * Mirrors `paymentPreflight` in transaction.js so the screen can state what the
 * buyer is short by before a password is typed and before anything is signed.
 * All values are integers; NSAT amounts must never pass through a float.
 */

/** The account keeps a two-reserve cushion, exactly as the signer enforces. */
export const RESERVE_MULTIPLIER = 2n;

const toBigInt = (value) => {
  // BigInt("") is 0n, which would silently turn a missing amount or balance
  // into "zero NSAT". Refuse an empty string before it can become a number.
  if (typeof value === "string" && value.trim() === "") return null;
  try {
    return BigInt(value);
  } catch {
    return null;
  }
};

/**
 * Minimum balance a transfer of `amount` needs: the amount itself, the network
 * fee, and the reserve cushion the source account must keep.
 */
export function transferRequirement({ amount, fee, reserve }) {
  const [amountValue, feeValue, reserveValue] = [amount, fee, reserve].map(toBigInt);
  if ([amountValue, feeValue, reserveValue].some((value) => value === null || value < 0n)) {
    throw new Error("checkout_amount_invalid");
  }
  return amountValue + feeValue + reserveValue * RESERVE_MULTIPLIER;
}

/** How much more NSAT the wallet needs, or 0n when the transfer fits. */
export function transferShortfall({ amount, balance, fee, reserve }) {
  const available = toBigInt(balance);
  if (available === null || available < 0n) throw new Error("checkout_balance_invalid");
  const required = transferRequirement({ amount, fee, reserve });
  return required > available ? required - available : 0n;
}

/** Grouped integer label for an NSAT amount, never a rounded number. */
export function formatNsat(value) {
  try {
    return BigInt(value).toLocaleString("en-US");
  } catch {
    return "—";
  }
}
