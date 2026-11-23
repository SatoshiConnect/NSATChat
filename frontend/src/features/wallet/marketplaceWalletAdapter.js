/**
 * Headless wallet boundary for Marketplace integrations.
 * No signing implementation is enabled here; never substitute server-held keys.
 */
export function createMarketplaceWalletAdapter(capabilities = {}) {
  const readAddress = capabilities.readAddress;
  const readBalance = capabilities.readBalance;
  return Object.freeze({
    canRead: typeof readAddress === "function" && typeof readBalance === "function",
    canSign: false,
    canTransfer: false,
    async readOnlyBalance(asset) {
      if (typeof readAddress !== "function" || typeof readBalance !== "function") {
        throw new Error("A user-linked wallet read adapter is not configured.");
      }
      const address = await readAddress();
      if (!address) throw new Error("No wallet is linked.");
      return { address, asset, balance: await readBalance({ address, asset }) };
    },
    async requestSignature() {
      throw new Error("Marketplace signing is disabled. No on-chain payment can be requested here.");
    },
  });
}
