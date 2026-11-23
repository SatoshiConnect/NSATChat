export const WALLET_REQUEST_PREFIX = "__SATOSHICORE_WALLET_REQUEST_V1__:";
export const WALLET_RECEIPT_PREFIX = "__SATOSHICORE_WALLET_RECEIPT_V1__:";
const ADDRESS_RE = /^G[A-Z2-7]{55}$/;
const HASH_RE = /^[A-F0-9]{64}$/;

export function createWalletRequestMessage({ address, amount = "" }) {
  const normalized = String(address || "").trim().toUpperCase();
  const exactAmount = String(amount || "").trim();
  if (!ADDRESS_RE.test(normalized)) throw new Error("invalid_wallet_address");
  if (exactAmount && !/^[1-9]\d{0,29}$/.test(exactAmount)) throw new Error("invalid_wallet_amount");
  return `${WALLET_REQUEST_PREFIX}${JSON.stringify({ v: 1, address: normalized, amount: exactAmount })}`;
}

export function parseWalletRequestMessage(value) {
  if (typeof value !== "string" || !value.startsWith(WALLET_REQUEST_PREFIX)) return null;
  try {
    const data = JSON.parse(value.slice(WALLET_REQUEST_PREFIX.length));
    if (data?.v !== 1 || !ADDRESS_RE.test(data.address || "")
      || (data.amount && !/^[1-9]\d{0,29}$/.test(data.amount))) return null;
    return { address: data.address, amount: data.amount || "" };
  } catch {
    return null;
  }
}

export function createWalletReceiptMessage({ hash, address, amount, ledger }) {
  const normalizedAddress = String(address || "").trim().toUpperCase();
  const normalizedHash = String(hash || "").trim().toUpperCase();
  const exactAmount = String(amount ?? "");
  const exactLedger = String(ledger ?? "");
  if (!HASH_RE.test(normalizedHash) || !ADDRESS_RE.test(normalizedAddress)
    || !/^[1-9]\d{0,29}$/.test(exactAmount) || (exactLedger && !/^\d{1,20}$/.test(exactLedger))) {
    throw new Error("invalid_wallet_receipt");
  }
  return `${WALLET_RECEIPT_PREFIX}${JSON.stringify({ v: 1, hash: normalizedHash, address: normalizedAddress, amount: exactAmount, ledger: exactLedger })}`;
}

export function parseWalletReceiptMessage(value) {
  if (typeof value !== "string" || !value.startsWith(WALLET_RECEIPT_PREFIX)) return null;
  try {
    const data = JSON.parse(value.slice(WALLET_RECEIPT_PREFIX.length));
    if (data?.v !== 1 || !HASH_RE.test(data.hash || "") || !ADDRESS_RE.test(data.address || "")
      || !/^[1-9]\d{0,29}$/.test(data.amount || "") || (data.ledger && !/^\d{1,20}$/.test(String(data.ledger)))) return null;
    return { hash: data.hash, address: data.address, amount: data.amount, ledger: String(data.ledger) };
  } catch {
    return null;
  }
}
