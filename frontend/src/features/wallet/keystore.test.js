import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  generateWalletKeypair,
  readKeystoreMeta,
  saveEncryptedWallet,
  unlockEncryptedWallet,
} from "./keystore.js";

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
}

describe("NSATChat device keystore", () => {
  it("stores only an encrypted secret and unlocks the same address", async () => {
    const storage = memoryStorage();
    const wallet = generateWalletKeypair();
    const saved = await saveEncryptedWallet(wallet.secret, "a long local wallet password", { storage });
    const stored = storage.getItem("satoshicore:messenger-keystore:v1");

    assert.equal(saved.address, wallet.address);
    assert.equal(readKeystoreMeta(storage).address, wallet.address);
    assert.equal(stored.includes(wallet.secret), false);
    assert.equal((await unlockEncryptedWallet("a long local wallet password", { storage })).address, wallet.address);
    await assert.rejects(unlockEncryptedWallet("incorrect password", { storage }), /wallet_unlock_failed/);
  });

  it("rejects short passwords and invalid recovery keys", async () => {
    const wallet = generateWalletKeypair();
    const storage = memoryStorage();
    await assert.rejects(saveEncryptedWallet(wallet.secret, "short", { storage }), /wallet_password_invalid/);
    await assert.rejects(saveEncryptedWallet("not-a-secret", "a long local wallet password", { storage }), /wallet_recovery_key_invalid/);
  });
});
