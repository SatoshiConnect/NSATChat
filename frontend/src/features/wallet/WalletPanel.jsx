import { useEffect, useState } from "react";
import { ArrowLeft, ExternalLink, WalletCards } from "lucide-react";
import { walletApi } from "./api";
import { useApp } from "../../components/layout/AppContext";
import { toast } from "../../services/toast";

const WALLET_ORIGIN = "https://wallet.satoshicore.org";

/**
 * Messenger hosts the real Wallet web app in a narrowly allowlisted iframe.
 * The frame stays on wallet.satoshicore.org, so its encrypted local keystore,
 * unlock flow, receive tools and transaction signing all remain Wallet-owned.
 */
export default function WalletPanel({ launch = null }) {
  const app = useApp();
  const [linkedWallet, setLinkedWallet] = useState(null);
  const [linkBusy, setLinkBusy] = useState(false);
  const [frameUrl, setFrameUrl] = useState(`${WALLET_ORIGIN}/messenger-embed/`);
  const [frameBusy, setFrameBusy] = useState(true);
  const [frameError, setFrameError] = useState("");

  useEffect(() => {
    let alive = true;
    walletApi.linkState()
      .then((state) => { if (alive) setLinkedWallet(state); })
      .catch(() => { if (alive) setLinkedWallet(null); });
    const refresh = () => walletApi.linkState()
      .then((state) => { if (alive) setLinkedWallet(state); })
      .catch(() => { if (alive) setLinkedWallet(null); });
    window.addEventListener("satoshicore:wallet-link-changed", refresh);
    return () => {
      alive = false;
      window.removeEventListener("satoshicore:wallet-link-changed", refresh);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    const request = launch;
    if (!request?.roomId) {
      const target = new URL("/messenger-embed/", WALLET_ORIGIN);
      if (["send", "receive"].includes(request?.view)) target.searchParams.set("view", request.view);
      Promise.resolve().then(() => {
        if (!alive) return;
        setFrameUrl(target.href);
        setFrameError("");
        setFrameBusy(true);
      });
      return () => { alive = false; };
    }

    Promise.resolve().then(() => {
      if (!alive) return;
      setFrameError("");
      setFrameBusy(true);
    });
    walletApi.chatRecipient(request.roomId)
      .then((recipient) => {
        const target = new URL("/messenger-embed/", WALLET_ORIGIN);
        if (recipient?.network !== "NSAT Mainnet ; October 2026 ; bc3098829fffc717"
          || !/^G[A-Z2-7]{55}$/.test(recipient?.address || "")) {
          throw new Error("recipient_unavailable");
        }
        target.searchParams.set("view", "send");
        target.searchParams.set("to", recipient.address);
        if (alive) setFrameUrl(target.href);
      })
      .catch((error) => {
        if (!alive) return;
        const code = error?.response?.data?.code;
        setFrameError(code === "recipient_wallet_not_connected"
          ? "This contact has not connected an NSAT Wallet yet. You can still open your Wallet and receive NSAT."
          : "Could not verify this contact’s Wallet. Open the Wallet without a recipient or try again.");
        setFrameUrl(`${WALLET_ORIGIN}/messenger-embed/`);
      });
    return () => { alive = false; };
  }, [launch]);

  const connectWallet = async () => {
    setLinkBusy(true);
    try {
      const result = await walletApi.startLink();
      const target = new URL(result.wallet_url);
      if (target.origin !== WALLET_ORIGIN || target.pathname !== "/connect/messenger/") {
        throw new Error("Invalid Wallet connection URL");
      }
      // Ownership proof happens on the Wallet origin; the chat backend only
      // receives the public address and a short-lived signature challenge.
      window.location.assign(target.href);
    } catch (error) {
      toast.error(error?.response?.data?.code === "wallet_link_unavailable"
        ? "Wallet linking is not available on this server version yet."
        : "Could not start the secure Wallet connection. Try again.");
      setLinkBusy(false);
    }
  };

  const disconnectWallet = async () => {
    if (!window.confirm("Disconnect this wallet from your Messenger account?")) return;
    setLinkBusy(true);
    try {
      await walletApi.disconnect();
      setLinkedWallet({ connected: false, address: "" });
    } catch {
      toast.error("Could not disconnect the Wallet. Try again.");
    } finally {
      setLinkBusy(false);
    }
  };

  const shortAddress = (address) => address ? `${address.slice(0, 10)}…${address.slice(-8)}` : "";

  return (
    <section className="wallet-panel wallet-panel--embedded" aria-label="SatoshiCore Wallet">
      <header className="wallet-panel__toolbar">
        <button type="button" className="wallet-panel__back" onClick={() => app.setSection("chats")}>
          <ArrowLeft size={18} /> <span>Back to chat</span>
        </button>
        <div className="wallet-panel__title"><WalletCards size={19} /><strong>Wallet</strong></div>
        <a className="wallet-panel__open" href={`${WALLET_ORIGIN}/`} target="_blank" rel="noreferrer">
          Open separately <ExternalLink size={15} />
        </a>
      </header>

      <div className="wallet-panel__linkbar">
        <span className="wallet-panel__linkstatus">
          {linkedWallet?.connected
            ? `Connected · ${shortAddress(linkedWallet.address)}`
            : "Connect your verified Wallet to receive payments from chat contacts"}
        </span>
        {linkedWallet?.connected ? (
          <button type="button" className="wallet-text-button wallet-text-button--danger" onClick={disconnectWallet} disabled={linkBusy}>
            Disconnect
          </button>
        ) : (
          <button type="button" className="btn btn--primary" onClick={connectWallet} disabled={linkBusy}>
            {linkBusy ? "Opening Wallet…" : "Connect Wallet"}
          </button>
        )}
      </div>

      {frameError ? <div className="wallet-error" role="alert">{frameError}</div> : null}
      {frameBusy ? <div className="wallet-panel__loading" role="status">Opening your secure Wallet…</div> : null}
      <iframe
        key={frameUrl}
        className={`wallet-panel__frame ${frameBusy ? "is-loading" : ""}`}
        src={frameUrl}
        title="SatoshiCore Wallet"
        referrerPolicy="strict-origin"
        allow="clipboard-read; clipboard-write"
        onLoad={() => { setFrameBusy(false); setFrameError(""); }}
        onError={() => { setFrameBusy(false); setFrameError("The Wallet site could not be loaded. Use “Open separately” to continue."); }}
      />
    </section>
  );
}
