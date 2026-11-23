import { useEffect, useMemo, useState } from "react";
import { Activity, ArrowDownLeft, ArrowLeft, ArrowUpRight, Check, Copy, QrCode, RefreshCw, ShieldCheck, WalletCards } from "lucide-react";
import { walletApi } from "./api";
import { useApp } from "../../components/layout/AppContext";
import { toast } from "../../services/toast";

const ADDRESS_RE = /^G[A-Z2-7]{55}$/;
const ADDRESS_KEY = "satoshicore:messenger-wallet-address:v1";
const MAINNET = "NSAT Mainnet ; October 2026 ; bc3098829fffc717";

function loadAddress() {
  try {
    const value = window.localStorage.getItem(ADDRESS_KEY) || "";
    return ADDRESS_RE.test(value) ? value : "";
  } catch {
    return "";
  }
}

function exactAmount(value) {
  if (!/^\d+$/.test(String(value ?? ""))) return "—";
  return BigInt(value).toLocaleString("en-US");
}

function shortAddress(value) {
  return value ? `${value.slice(0, 9)}…${value.slice(-8)}` : "";
}

function formatDate(epoch) {
  const date = new Date(Number(epoch) * 1000);
  return Number.isNaN(date.getTime()) ? "Date unavailable" : new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short",
  }).format(date);
}

/**
 * NSATChat's first-party wallet surface. This is a new Messenger feature, not
 * an embedded route from wallet.satoshicore.org. The server contract currently
 * supports authenticated read-only account and history queries only.
 */
export default function WalletPanel({ launch = null }) {
  const app = useApp();
  const [section, setSection] = useState(launch?.view === "send" ? "send" : launch?.view === "receive" ? "receive" : "overview");
  const [address, setAddress] = useState(loadAddress);
  const [addressInput, setAddressInput] = useState("");
  const [wallet, setWallet] = useState(null);
  const [qr, setQr] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recipient, setRecipient] = useState("");
  const [requestAmount, setRequestAmount] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => {
      if (!active) return;
      setSection(launch?.view === "send" ? "send" : launch?.view === "receive" ? "receive" : "overview");
      setRequestAmount(launch?.amount || "");
      setRecipient(ADDRESS_RE.test(launch?.to || "") ? launch.to : "");
    });
    if (launch?.roomId && !launch?.to) {
      walletApi.chatRecipient(launch.roomId)
        .then((peer) => {
          if (!active) return;
          if (peer?.network !== MAINNET || !ADDRESS_RE.test(peer.address || "")) return;
          if (!launch.to) setRecipient(peer.address);
        })
        .catch(() => { if (active && !launch?.to) setRecipient(""); });
    }
    return () => { active = false; };
  }, [launch]);

  useEffect(() => {
    let active = true;
    if (!address) return () => { active = false; };

    Promise.resolve().then(() => {
      if (!active) return null;
      setBusy(true);
      setError("");
      return walletApi.read(address);
    })
      .then((result) => {
        if (!active || !result) return;
        if (result?.network !== MAINNET || result?.address !== address) throw new Error("mainnet_unverified");
        setWallet(result);
      })
      .catch((failure) => {
        if (!active) return;
        setWallet(null);
        const code = failure?.response?.data?.code;
        setError(code === "wallet_unavailable" || code === "mainnet_unverified"
          ? "NSAT Mainnet is temporarily unavailable. Your address is still saved on this device."
          : "That address could not be verified on NSAT Mainnet.");
      })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [address, refreshKey]);

  useEffect(() => {
    let active = true;
    if (!address || section !== "receive") return () => { active = false; };
    import("qrcode").then(({ default: QRCode }) => QRCode.toDataURL(address, {
      width: 224, margin: 1, errorCorrectionLevel: "M",
      color: { dark: "#111827", light: "#ffffff" },
    })).then((data) => { if (active) setQr(data); }).catch(() => { if (active) setQr(""); });
    return () => { active = false; };
  }, [address, section]);

  const history = useMemo(() => Array.isArray(wallet?.history) ? wallet.history : [], [wallet]);

  const saveAddress = async (event) => {
    event.preventDefault();
    const value = addressInput.trim().toUpperCase();
    if (!ADDRESS_RE.test(value)) {
      setError("Enter a valid NSAT public address (starts with G).");
      return;
    }
    try { window.localStorage.setItem(ADDRESS_KEY, value); } catch { /* The view still works for this session. */ }
    setWallet(null);
    setQr("");
    setError("");
    setAddress(value);
    setAddressInput("");
  };

  const copyAddress = async () => {
    try {
      await navigator.clipboard.writeText(address);
      toast.success("NSAT address copied.");
    } catch {
      toast.error("Could not copy this address. Select and copy it instead.");
    }
  };

  const actions = [
    { key: "send", label: "Send", icon: ArrowUpRight },
    { key: "receive", label: "Receive", icon: ArrowDownLeft },
    { key: "activity", label: "Activity", icon: Activity },
  ];

  return (
    <section className="wallet-native" aria-label="SatoshiCore NSAT Wallet">
      <header className="wallet-native__header">
        <button type="button" className="wallet-native__back" onClick={() => app.setSection("chats")}>
          <ArrowLeft size={18} /> <span>Back to chat</span>
        </button>
        <div className="wallet-native__brand"><WalletCards size={19} /><strong>Wallet</strong><span>NSAT Mainnet</span></div>
        <button type="button" className="wallet-native__refresh" onClick={() => address && setRefreshKey((value) => value + 1)} disabled={!address || busy} aria-label="Refresh wallet">
          <RefreshCw size={18} className={busy ? "is-spinning" : ""} />
        </button>
      </header>

      <div className="wallet-native__body">
        {!address ? (
          <div className="wallet-native__welcome">
            <div className="wallet-native__mark"><WalletCards size={30} /></div>
            <p className="wallet-native__eyebrow">SATOSHICORE WALLET</p>
            <h1>Your NSAT wallet, inside chat</h1>
            <p className="wallet-native__lead">View a public NSAT address and its on-chain activity without leaving Messenger.</p>
            <form className="wallet-native__address-form" onSubmit={saveAddress}>
              <label htmlFor="native-wallet-address">NSAT public address</label>
              <input id="native-wallet-address" value={addressInput} onChange={(event) => setAddressInput(event.target.value)} placeholder="G…" autoCapitalize="characters" autoComplete="off" spellCheck="false" />
              <button type="submit" className="btn btn--primary">View wallet</button>
            </form>
            <p className="wallet-native__privacy"><ShieldCheck size={16} /> This is a public address only. Never enter a seed phrase or private key here.</p>
            {error ? <p className="wallet-native__error" role="alert">{error}</p> : null}
            <p className="wallet-native__availability">Native wallet creation and transaction signing are not available in this build yet.</p>
          </div>
        ) : (
          <>
            <div className="wallet-native__account-row">
              <div><span className="wallet-native__eyebrow">YOUR NSAT ADDRESS</span><strong title={address}>{shortAddress(address)}</strong></div>
              <button type="button" className="wallet-native__icon-button" aria-label="Copy address" onClick={copyAddress}><Copy size={17} /></button>
            </div>

            <section className="wallet-native__balance-card" aria-label="Wallet balance">
              <div className="wallet-native__balance-label"><span>NSAT balance</span><span className="wallet-native__network-dot" />{wallet?.account_status === "active" ? "Mainnet" : wallet?.account_status === "not_found" ? "Not activated" : "Checking"}</div>
              <strong>{busy ? "…" : wallet?.account_status === "active" ? exactAmount(wallet.balance) : wallet?.account_status === "not_found" ? "0" : "—"}</strong>
              <span>NSAT · whole units</span>
            </section>

            <div className="wallet-native__actions">
              {actions.map(({ key, label, icon: Icon }) => (
                <button type="button" key={key} className={section === key ? "is-active" : ""} onClick={() => setSection(key)}>
                  <span><Icon size={20} /></span>{label}
                </button>
              ))}
            </div>

            {error ? <p className="wallet-native__error" role="alert">{error}</p> : null}

            {section === "overview" ? (
              <section className="wallet-native__activity">
                <div className="wallet-native__section-title"><h2>Recent activity</h2><button type="button" onClick={() => setSection("activity")}>See all</button></div>
                {history.length ? history.slice(0, 5).map((item) => <ActivityRow key={item.hash} item={item} />) : <div className="wallet-native__empty">{busy ? "Loading activity…" : "No transactions to show yet."}</div>}
              </section>
            ) : null}

            {section === "activity" ? (
              <section className="wallet-native__activity">
                <div className="wallet-native__section-title"><h2>Activity</h2><span>{history.length} transactions</span></div>
                {wallet?.history_status === "unavailable" ? <div className="wallet-native__notice">Transaction history is temporarily unavailable. The balance above is read from Mainnet.</div> : null}
                {history.length ? history.map((item) => <ActivityRow key={item.hash} item={item} />) : <div className="wallet-native__empty">{busy ? "Loading activity…" : "No transactions to show yet."}</div>}
              </section>
            ) : null}

            {section === "receive" ? (
              <section className="wallet-native__receive">
                <div className="wallet-native__section-title"><h2>Receive NSAT</h2></div>
                <p>Share this address with someone who wants to send you NSAT.</p>
                <div className="wallet-native__qr">{qr ? <img src={qr} alt="QR code for NSAT receive address" /> : <QrCode size={40} />}</div>
                <code>{address}</code>
                <button type="button" className="btn btn--primary" onClick={copyAddress}><Copy size={16} /> Copy address</button>
                <p className="wallet-native__privacy"><ShieldCheck size={16} /> Check the NSAT network before sending. Transfers are public and irreversible.</p>
              </section>
            ) : null}

            {section === "send" ? (
              <section className="wallet-native__send">
                <div className="wallet-native__section-title"><h2>Send NSAT</h2></div>
                {recipient ? <p className="wallet-native__recipient">Chat recipient <code>{shortAddress(recipient)}</code></p> : null}
                {requestAmount ? <p className="wallet-native__recipient">Requested amount <strong>{exactAmount(requestAmount)} NSAT</strong></p> : null}
                <div className="wallet-native__notice"><ShieldCheck size={18} /><span>On-chain sending is not enabled in NSATChat yet. This server currently supports verified balance and activity reads only. No transfer will be submitted from this screen.</span></div>
                <p className="wallet-native__availability">A native send flow needs local key creation or recovery, transaction review, and device-side signing before it can safely send NSAT.</p>
              </section>
            ) : null}

            <button type="button" className="wallet-native__change" onClick={() => { try { window.localStorage.removeItem(ADDRESS_KEY); } catch { /* ignore */ } setAddress(""); setWallet(null); setQr(""); setSection("overview"); }}>
              Change or clear viewed address
            </button>
          </>
        )}
      </div>
    </section>
  );
}

function ActivityRow({ item }) {
  const isIncoming = item.direction === "in";
  const label = isIncoming ? "Received" : item.direction === "out" ? "Sent" : "Self transfer";
  return (
    <article className="wallet-native__activity-row">
      <div className={`wallet-native__activity-icon ${isIncoming ? "is-in" : ""}`}>{isIncoming ? <ArrowDownLeft size={18} /> : <ArrowUpRight size={18} />}</div>
      <div className="wallet-native__activity-main"><strong>{label}</strong><span>{formatDate(item.close_time)}</span><small>{item.counterparty ? shortAddress(item.counterparty) : item.kind}</small></div>
      <div className="wallet-native__activity-amount"><strong className={isIncoming ? "is-in" : ""}>{isIncoming ? "+" : "−"}{exactAmount(item.amount)}</strong><span>NSAT</span></div>
      {item.success ? <Check size={14} className="wallet-native__success" aria-label="Confirmed" /> : null}
    </article>
  );
}
