import { Keypair } from "@stellar/stellar-sdk";

export const NSAT_NETWORK_ID = "NSAT Mainnet ; October 2026 ; bc3098829fffc717";
export const NSAT_BASE_FEE_POLICY = 10n;
export const NSAT_MAX_TRANSFER = 9223372036854775807n;

const u32 = (value) => Uint8Array.of((value >>> 24) & 255, (value >>> 16) & 255, (value >>> 8) & 255, value & 255);
function unsigned(value, length) {
  let number = BigInt(value);
  const bytes = new Uint8Array(length);
  for (let index = length - 1; index >= 0; index -= 1) {
    bytes[index] = Number(number & 255n);
    number >>= 8n;
  }
  if (number !== 0n) throw new Error("transaction_integer_overflow");
  return bytes;
}
function signed128(value) {
  const n = BigInt(value);
  if (n < 0n || n > ((1n << 127n) - 1n)) throw new Error("transaction_amount_invalid");
  return unsigned(n, 16);
}
function concat(...values) {
  const result = new Uint8Array(values.reduce((length, value) => length + value.length, 0));
  let offset = 0;
  for (const value of values) { result.set(value, offset); offset += value.length; }
  return result;
}
function accountId(publicKey) { return concat(u32(0), publicKey); }
function paymentOperation(source, destination, amount, createAccount) {
  return createAccount
    ? concat(u32(1), accountId(source), u32(0), accountId(destination), signed128(amount))
    : concat(u32(1), accountId(source), u32(1), accountId(destination), u32(0), signed128(amount));
}
function transactionV0(source, fee, sequence, operation) {
  return concat(source, u32(fee), unsigned(sequence, 8), u32(0), u32(0), u32(1), operation, u32(0));
}
function transactionV1SelfOpen(source) {
  // NSAT Core V_16 allows a key to open its own zero-balance account. The
  // source account does not exist yet, so this exact one-op transaction has
  // no fee bid or sequence number and creates source == destination.
  const operation = concat(
    u32(1), u32(0), source, // present operation source: this new account
    u32(0),                 // CREATE_ACCOUNT
    u32(0), source,         // destination account ID
    signed128(0),           // zero starting balance
  );
  return concat(
    u32(0), source,         // TransactionV1 source account
    u32(0),                 // fee
    unsigned(0, 8),         // sequence number
    u32(0),                 // PRECOND_NONE
    u32(0),                 // MEMO_NONE
    u32(1), operation,      // exactly one operation
    u32(0),                 // transaction extension
  );
}
function base64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}
function hex(bytes) { return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(""); }

export function parsePositiveAmount(raw) {
  const normalized = String(raw ?? "").replace(/[,_\s]/g, "");
  if (!/^\d+$/.test(normalized)) throw new Error("amount_whole_number_required");
  const amount = BigInt(normalized);
  if (amount <= 0n || amount > NSAT_MAX_TRANSFER) throw new Error("amount_out_of_range");
  return amount;
}

export function paymentPreflight({ sourceAddress, destinationAddress, amount, balance, sequence, baseFee, baseReserve, destinationExists, destinationCreationMinimum, accountReserveFloor }) {
  if (!/^G[A-Z2-7]{55}$/.test(String(sourceAddress || ""))) throw new Error("source_address_invalid");
  try { Keypair.fromPublicKey(sourceAddress); } catch { throw new Error("source_address_invalid"); }
  if (!/^G[A-Z2-7]{55}$/.test(String(destinationAddress || ""))) throw new Error("destination_address_invalid");
  try { Keypair.fromPublicKey(destinationAddress); } catch { throw new Error("destination_address_invalid"); }
  if (destinationAddress === sourceAddress) throw new Error("self_transfer_not_allowed");
  const amountValue = typeof amount === "bigint" ? amount : parsePositiveAmount(amount);
  if (!Number.isSafeInteger(baseFee) || BigInt(baseFee) !== NSAT_BASE_FEE_POLICY) throw new Error("fee_policy_unverified");
  const balanceValue = BigInt(balance);
  const reserveValue = BigInt(baseReserve);
  const seq = BigInt(sequence);
  if (balanceValue < 0n || reserveValue < 0n || seq < 0n || seq >= ((1n << 63n) - 1n)) throw new Error("account_state_invalid");
  const create = !destinationExists;
  const defaultReserveFloor = reserveValue * 2n;
  const accountFloor = accountReserveFloor == null ? defaultReserveFloor : BigInt(accountReserveFloor);
  const destinationFloor = destinationCreationMinimum == null ? defaultReserveFloor : BigInt(destinationCreationMinimum);
  if (accountFloor < 0n || destinationFloor < 0n) throw new Error("account_state_invalid");
  if (create && amountValue < destinationFloor) throw new Error("destination_creation_reserve_too_low");
  const total = amountValue + NSAT_BASE_FEE_POLICY;
  if (total + accountFloor > balanceValue) throw new Error("insufficient_balance_or_reserve");
  return { amount: amountValue, fee: Number(NSAT_BASE_FEE_POLICY), sequence: seq + 1n, create, total, reserveFloor: accountFloor };
}

/** Build the NSAT TransactionV0 signed envelope used by the Mainnet node. */
export async function buildSignedPayment({ secret, destinationAddress, preflight }) {
  const keypair = Keypair.fromSecret(String(secret).trim().toUpperCase());
  const source = new Uint8Array(keypair.rawPublicKey());
  const destination = new Uint8Array(Keypair.fromPublicKey(destinationAddress).rawPublicKey());
  const operation = paymentOperation(source, destination, preflight.amount, preflight.create);
  const tx = transactionV0(source, preflight.fee, preflight.sequence, operation);
  const networkHash = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(NSAT_NETWORK_ID)));
  const payload = new Uint8Array(await crypto.subtle.digest("SHA-256", concat(networkHash, u32(2), u32(0), tx)));
  const signature = new Uint8Array(keypair.sign(payload));
  try {
    const envelope = concat(u32(0), tx, u32(1), source.subarray(28), u32(64), signature);
    return { envelopeXdr: base64(envelope), hash: hex(payload), sourceAddress: keypair.publicKey() };
  } finally {
    signature.fill(0);
    source.fill(0);
    destination.fill(0);
  }
}

/**
 * Build the protocol V_16 zero-balance self-open for this wallet. This does
 * not move NSAT or pay a network fee. The server independently verifies this
 * exact envelope shape and the live Mainnet self-open policy before relay.
 */
export async function buildSignedSelfOpen({ secret, address }) {
  if (!/^G[A-Z2-7]{55}$/.test(String(address || ""))) throw new Error("source_address_invalid");
  const keypair = Keypair.fromSecret(String(secret).trim().toUpperCase());
  if (keypair.publicKey() !== address) throw new Error("wallet_address_mismatch");
  const source = new Uint8Array(keypair.rawPublicKey());
  const tx = transactionV1SelfOpen(source);
  const networkHash = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(NSAT_NETWORK_ID)));
  // Signature payload is Hash( Hash(networkID) || ENVELOPE_TYPE_TX || TxV1 ).
  const payload = new Uint8Array(await crypto.subtle.digest("SHA-256", concat(networkHash, u32(2), tx)));
  const signature = new Uint8Array(keypair.sign(payload));
  try {
    const envelope = concat(
      u32(2), tx,           // ENVELOPE_TYPE_TX / TransactionV1
      u32(1), source.subarray(28), u32(signature.length), signature,
    );
    return { envelopeXdr: base64(envelope), hash: hex(payload), sourceAddress: keypair.publicKey() };
  } finally {
    signature.fill(0);
    source.fill(0);
  }
}
