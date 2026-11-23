import { useEffect, useRef, useState } from "react";
import { ArrowLeft, WalletCards } from "lucide-react";
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
  const frameRef = useRef(null);
  const pendingLinkToken = useRef("");
  const linkConfirmBusy = useRef(false);

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

  useEffect(() => {
    const handleWalletMessage = async (event) => {
      const proof = event.data;
      if (event.origin !== WALLET_ORIGIN
        || event.source !== frameRef.current?.contentWindow
        || proof?.type !== "satoshicore:wallet-link-proof"
        || typeof proof.token !== "string"
        || proof.token !== pendingLinkToken.current
        || !/^G[A-Z2-7]{55}$/.test(proof.address || "")
        || typeof proof.signature !== "string"
        || linkConfirmBusy.current) return;

      linkConfirmBusy.current = true;
      setLinkBusy(true);
      try {
        await walletApi.confirmLink({
          token: proof.token,
          address: proof.address,
          signature: proof.signature,
        });
        const state = await walletApi.linkState();
        setLinkedWallet(state);
        frameRef.current?.contentWindow?.postMessage(
          { type: "satoshicore:wallet-link-result", ok: true },
          WALLET_ORIGIN,
        );
        pendingLinkToken.current = "";
        toast.success("Wallet connected to Messenger.");
      } catch (error) {
        const code = error?.response?.data?.code;
        frameRef.current?.contentWindow?.postMessage(
          {
            type: "satoshicore:wallet-link-result",
            ok: false,
            code: code === "wallet_link_expired" ? "expired" : "verification_failed",
          },
          WALLET_ORIGIN,
        );
      } finally {
        linkConfirmBusy.current = false;
        setLinkBusy(false);
      }
    };
    window.addEventListener("message", handleWalletMessage);
    return () => window.removeEventListener("message", handleWalletMessage);
  }, []);

  const connectWallet = async () => {
    setLinkBusy(true);
    try {
      const result = await walletApi.startLink();
      const target = new URL(result.wallet_url);
      if (target.origin !== WALLET_ORIGIN || target.pathname !== "/messenger-embed/") {
        throw new Error("Invalid Wallet connection URL");
      }
      const challenge = new URLSearchParams(target.hash.slice(1));
      const token = challenge.get("token") || "";
      const message = challenge.get("message") || "";
      if (!/^[A-Za-z0-9_-]{43}$/.test(token) || !message.includes(`Challenge: ${token}`)) {
        throw new Error("Invalid Wallet challenge");
      }
      // Keep the Wallet on its own origin inside the chat frame. Its key signs
      // the one-use challenge; only that public proof returns to this page.
      const embedded = new URL("/messenger-embed/", WALLET_ORIGIN);
      embedded.hash = target.hash;
      pendingLinkToken.current = token;
      setFrameError("");
      setFrameBusy(true);
      setFrameUrl(embedded.href);
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
        <span className="wallet-panel__secure-label">Wallet stays in chat</span>
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
          {linkBusy ? "Preparing connection…" : "Connect Wallet"}
          </button>
        )}
      </div>

      {frameError ? <div className="wallet-error" role="alert">{frameError}</div> : null}
      {frameBusy ? <div className="wallet-panel__loading" role="status">Opening your secure Wallet…</div> : null}
      <iframe
        key={frameUrl}
        ref={frameRef}
        className={`wallet-panel__frame ${frameBusy ? "is-loading" : ""}`}
        src={frameUrl}
        title="SatoshiCore Wallet"
        referrerPolicy="strict-origin"
        allow="clipboard-read; clipboard-write"
        onLoad={() => { setFrameBusy(false); setFrameError(""); setLinkBusy(false); }}
        onError={() => { setFrameBusy(false); setLinkBusy(false); setFrameError("The Wallet could not be loaded. Check the network connection and retry."); }}
      />
    </section>
  );
}
