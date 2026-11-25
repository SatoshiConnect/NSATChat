import { createRoot } from "react-dom/client";
import { Keypair } from "@stellar/stellar-sdk";
import { AppContext } from "../../src/components/layout/AppContext";
import { saveEncryptedWallet } from "../../src/features/wallet/keystore";
import WalletPanel from "../../src/features/wallet/WalletPanel";

const secret = Keypair.fromRawEd25519Seed(new Uint8Array(32).fill(77)).secret();
if (!localStorage.getItem("satoshicore:messenger-keystore:v1")) {
  await saveEncryptedWallet(secret, "fixture-password");
}
createRoot(document.getElementById("root")).render(
  <AppContext.Provider value={{ setSection() {} }}><WalletPanel /></AppContext.Provider>,
);
