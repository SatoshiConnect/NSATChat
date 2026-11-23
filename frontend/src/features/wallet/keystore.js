import { Keypair } from "@stellar/stellar-sdk";

const STORAGE_KEY = "satoshicore:messenger-keystore:v1";
const ITERATIONS = 600_000;
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });

function toBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function fromBase64(value) {
  const binary = atob(value);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function cryptoApi(provider) {
  const api = provider || globalThis.crypto;
  if (!api?.subtle || !api?.getRandomValues) throw new Error("secure_crypto_unavailable");
  return api;
}

async function deriveEncryptionKey(password, salt, api) {
  if (typeof password !== "string" || password.length < 10 || password.length > 1024) {
    throw new Error("wallet_password_invalid");
  }
  const material = await api.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveKey"]);
  return api.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations: ITERATIONS },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

export function generateWalletKeypair() {
  const keypair = Keypair.random();
  return { address: keypair.publicKey(), secret: keypair.secret() };
}

export function validateWalletSecret(secret) {
  if (typeof secret !== "string" || !/^S[A-Z2-7]{55}$/.test(secret.trim().toUpperCase())) {
    throw new Error("wallet_recovery_key_invalid");
  }
  const keypair = Keypair.fromSecret(secret.trim().toUpperCase());
  return { address: keypair.publicKey(), secret: keypair.secret() };
}

export function readKeystoreMeta(storage = globalThis.localStorage) {
  try {
    const value = JSON.parse(storage?.getItem(STORAGE_KEY) || "null");
    if (value?.version !== 1 || !/^G[A-Z2-7]{55}$/.test(value.address || "")
      || typeof value.salt !== "string" || typeof value.iv !== "string"
      || typeof value.ciphertext !== "string") return null;
    return { address: value.address };
  } catch {
    return null;
  }
}

export async function saveEncryptedWallet(secret, password, {
  storage = globalThis.localStorage,
  cryptoProvider,
} = {}) {
  if (!storage?.setItem) throw new Error("wallet_storage_unavailable");
  const wallet = validateWalletSecret(secret);
  const api = cryptoApi(cryptoProvider);
  const salt = api.getRandomValues(new Uint8Array(16));
  const iv = api.getRandomValues(new Uint8Array(12));
  const key = await deriveEncryptionKey(password, salt, api);
  const ciphertext = await api.subtle.encrypt({ name: "AES-GCM", iv }, key, encoder.encode(wallet.secret));
  const record = {
    version: 1,
    address: wallet.address,
    kdf: "PBKDF2-SHA256",
    iterations: ITERATIONS,
    cipher: "AES-256-GCM",
    salt: toBase64(salt),
    iv: toBase64(iv),
    ciphertext: toBase64(new Uint8Array(ciphertext)),
  };
  storage.setItem(STORAGE_KEY, JSON.stringify(record));
  return { address: wallet.address };
}

export async function unlockEncryptedWallet(password, {
  storage = globalThis.localStorage,
  cryptoProvider,
} = {}) {
  const api = cryptoApi(cryptoProvider);
  let record;
  try { record = JSON.parse(storage?.getItem(STORAGE_KEY) || "null"); } catch { record = null; }
  if (record?.version !== 1 || record.kdf !== "PBKDF2-SHA256" || record.iterations !== ITERATIONS
    || record.cipher !== "AES-256-GCM" || !/^G[A-Z2-7]{55}$/.test(record.address || "")) {
    throw new Error("wallet_keystore_invalid");
  }
  try {
    const salt = fromBase64(record.salt);
    const iv = fromBase64(record.iv);
    const key = await deriveEncryptionKey(password, salt, api);
    const clear = await api.subtle.decrypt({ name: "AES-GCM", iv }, key, fromBase64(record.ciphertext));
    const wallet = validateWalletSecret(decoder.decode(clear));
    if (wallet.address !== record.address) throw new Error("wallet_address_mismatch");
    return wallet;
  } catch {
    throw new Error("wallet_unlock_failed");
  }
}

export function removeEncryptedWallet(storage = globalThis.localStorage) {
  storage?.removeItem(STORAGE_KEY);
}

export const WALLET_KDF_ITERATIONS = ITERATIONS;
