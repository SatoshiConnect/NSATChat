import { Keypair } from "@stellar/stellar-sdk";

const TOKEN_RE = /^[A-Za-z0-9_-]{43}$/;
const WALLET_ORIGIN = "https://wallet.satoshicore.org";
const WALLET_PATH = "/messenger-embed/";
const MESSAGE_PREFIX = "SatoshiCore Messenger wallet link v1\nOrigin: https://chat.satoshicore.org\n";

export function readWalletLinkChallenge(walletUrl) {
  const url = new URL(walletUrl);
  if (url.origin !== WALLET_ORIGIN || url.pathname !== WALLET_PATH) throw new Error("wallet_link_invalid_url");
  const params = new URLSearchParams(url.hash.slice(1));
  const token = params.get("token") || "";
  const message = params.get("message") || "";
  if (!TOKEN_RE.test(token) || !message.startsWith(MESSAGE_PREFIX)) throw new Error("wallet_link_invalid_challenge");
  return { token, message };
}

export function signWalletLinkChallenge(secret, expectedAddress, message) {
  const keypair = Keypair.fromSecret(String(secret || "").trim().toUpperCase());
  if (keypair.publicKey() !== expectedAddress) throw new Error("wallet_address_mismatch");
  const signature = keypair.sign(new TextEncoder().encode(message));
  let binary = "";
  for (const byte of signature) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
