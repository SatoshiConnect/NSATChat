import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowDownLeft, ArrowLeft, ArrowUpRight, Check, Copy, QrCode, RefreshCw, ShieldCheck, WalletCards } from "lucide-react";
import { walletApi } from "./api";
import { useApp } from "../../components/layout/AppContext";
import { toast } from "../../services/toast";
import { generateWalletKeypair, readKeystoreMeta, saveEncryptedWallet, unlockEncryptedWallet } from "./keystore";
import { readWalletLinkChallenge, signWalletLinkChallenge } from "./walletLink";
import { buildSignedPayment, paymentPreflight, parsePositiveAmount } from "./transaction";
import { createWalletReceiptMessage } from "./paymentRequest";
import { sendText } from "../../store/actions";
import MarketplaceCheckout from "./MarketplaceCheckout";

const ADDRESS_RE = /^G[A-Z2-7]{55}$/;
const ADDRESS_KEY = "satoshicore:messenger-wallet-address:v1";
const MAINNET = "NSAT Mainnet ; October 2026 ; bc3098829fffc717";

function loadAddress() {
  try {
    const value = window.localStorage.getItem(ADDRESS_KEY) || "";
    if (ADDRESS_RE.test(value)) return value;
  } catch {
    // Continue with the encrypted keystore metadata when local storage is unavailable.
  }
  return readKeystoreMeta()?.address || "";
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
 * an embedded route from wallet.satoshicore.org. Signing stays in this
 * browser; authenticated server routes verify and relay signed Mainnet XDR.
 */
export default function WalletPanel({ launch = null }) {
  const app = useApp();
  const [section, setSection] = useState(launch?.view === "send" ? "send" : launch?.view === "receive" ? "receive" : "overview");
  const [address, setAddress] = useState(loadAddress);
  const [ownsWallet, setOwnsWallet] = useState(() => {
    const ownedAddress = readKeystoreMeta()?.address;
    return Boolean(ownedAddress && ownedAddress === loadAddress());
  });
  const [unlocked, setUnlocked] = useState(false);
  const [keyFlow, setKeyFlow] = useState("");
  const [pendingWallet, setPendingWallet] = useState(null);
  const [recoveryKey, setRecoveryKey] = useState("");
  const [walletPassword, setWalletPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [backupConfirmed, setBackupConfirmed] = useState(false);
  const [keyBusy, setKeyBusy] = useState(false);
  const [keyError, setKeyError] = useState("");
  const [addressInput, setAddressInput] = useState("");
  const [wallet, setWallet] = useState(null);
  const [qr, setQr] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recipient, setRecipient] = useState("");
  const [requestAmount, setRequestAmount] = useState("");
  const [sendAmount, setSendAmount] = useState("");
  const [sendReview, setSendReview] = useState(null);
  const [sendBusy, setSendBusy] = useState(false);
  const [txStatus, setTxStatus] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [accountLink, setAccountLink] = useState({ loading: true, connected: false, address: "", error: "" });
  const [linkBusy, setLinkBusy] = useState(false);
  const [confirmUnlink, setConfirmUnlink] = useState(false);
  const signingSecretRef = useRef("");
  const postedReceiptHashesRef = useRef(new Set());

  useEffect(() => () => { signingSecretRef.current = ""; }, []);

  useEffect(() => {
    let active = true;
    walletApi.linkMe()
      .then((result) => {
        if (active) setAccountLink({ loading: false, connected: Boolean(result.connected), address: result.address || "", error: "" });
      })
      .catch(() => {
        if (active) setAccountLink({ loading: false, connected: false, address: "", error: "Wallet account status is temporarily unavailable." });
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => {
      if (!active) return;
      setSection(launch?.view === "send" ? "send" : launch?.view === "receive" ? "receive" : "overview");
      setRequestAmount(launch?.amount || "");
      setSendAmount(launch?.amount || "");
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
    setOwnsWallet(readKeystoreMeta()?.address === value);
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

  const beginCreateWallet = () => {
    setKeyError("");
    setRecoveryKey("");
    setWalletPassword("");
    setPasswordConfirm("");
    setBackupConfirmed(false);
    setPendingWallet(generateWalletKeypair());
    setKeyFlow("create");
  };

  const persistWallet = async (secret) => {
    setKeyBusy(true);
    setKeyError("");
    try {
      const saved = await saveEncryptedWallet(secret, walletPassword);
      signingSecretRef.current = secret;
      setAddress(saved.address);
      setOwnsWallet(true);
      setUnlocked(true);
      try { window.localStorage.setItem(ADDRESS_KEY, saved.address); } catch { /* Keystore remains the source of truth. */ }
      setKeyFlow("");
      setPendingWallet(null);
      setRecoveryKey("");
      setWalletPassword("");
      setPasswordConfirm("");
      setSection("overview");
    } catch (failure) {
      setKeyError(failure?.message === "wallet_password_invalid" ? "Use a password with at least 10 characters." : "The wallet could not be secured on this device. Check storage and try again.");
    } finally {
      setKeyBusy(false);
    }
  };

  const submitCreateWallet = async (event) => {
    event.preventDefault();
    if (!pendingWallet || !backupConfirmed) return;
    if (walletPassword !== passwordConfirm) {
      setKeyError("The passwords do not match.");
      return;
    }
    await persistWallet(pendingWallet.secret);
  };

  const submitRestoreWallet = async (event) => {
    event.preventDefault();
    setKeyError("");
    if (walletPassword !== passwordConfirm) {
      setKeyError("The passwords do not match.");
      return;
    }
    await persistWallet(recoveryKey.trim().toUpperCase());
  };

  const submitUnlockWallet = async (event) => {
    event.preventDefault();
    setKeyBusy(true);
    setKeyError("");
    try {
      const restored = await unlockEncryptedWallet(walletPassword);
      signingSecretRef.current = restored.secret;
      setUnlocked(true);
      setWalletPassword("");
      setKeyFlow("");
    } catch {
      setKeyError("That password did not unlock this wallet.");
    } finally {
      setKeyBusy(false);
    }
  };

  const lockWallet = () => {
    signingSecretRef.current = "";
    setUnlocked(false);
    setKeyFlow("");
    setWalletPassword("");
  };

  const connectWalletToAccount = async () => {
    setError("");
    if (!ownsWallet) {
      setError("A view-only address cannot be connected. Restore or create a wallet you control first.");
      return;
    }
    if (!signingSecretRef.current || !unlocked) {
      setKeyError("Unlock this wallet to prove ownership and connect it to your SatoshiCore account.");
      setKeyFlow("unlock");
      return;
    }
    setLinkBusy(true);
    try {
      const challengeResponse = await walletApi.linkStart();
      const { token, message } = readWalletLinkChallenge(challengeResponse.wallet_url);
      const signature = signWalletLinkChallenge(signingSecretRef.current, address, message);
      const result = await walletApi.linkConfirm(token, address, signature);
      setAccountLink({ loading: false, connected: Boolean(result.connected), address: result.address || address, error: "" });
      toast.success("NSAT wallet connected to your SatoshiCore account.");
    } catch (failure) {
      const code = failure?.response?.data?.code || failure?.message || "";
      const messages = {
        wallet_already_linked: "Another NSAT wallet is already linked to this account. Disconnect it before connecting a different one.",
        wallet_address_in_use: "This NSAT wallet is linked to another SatoshiCore account.",
        wallet_signature_invalid: "Wallet ownership could not be verified. Unlock the wallet and try again.",
        wallet_link_expired: "The link request expired. Start again to connect your wallet.",
        wallet_address_mismatch: "The unlocked wallet does not match this address.",
      };
      setError(messages[code] || "The wallet could not be connected to your account. Try again.");
    } finally {
      setLinkBusy(false);
    }
  };

  const disconnectWalletFromAccount = async () => {
    setLinkBusy(true);
    try {
      const result = await walletApi.unlink();
      setAccountLink({ loading: false, connected: Boolean(result.connected), address: result.address || "", error: "" });
      setConfirmUnlink(false);
      toast.success("NSAT wallet disconnected from your SatoshiCore account.");
    } catch {
      setError("The wallet could not be disconnected right now. Try again.");
    } finally {
      setLinkBusy(false);
    }
  };

  const reviewSend = async (event) => {
    event.preventDefault();
    setError("");
    setTxStatus(null);
    if (!ownsWallet) { setError("This address is view-only. Restore or create a wallet you control to send NSAT."); return; }
    if (!signingSecretRef.current || !unlocked) { setKeyError("Unlock your wallet before preparing a transfer."); setKeyFlow("unlock"); return; }
    const destination = recipient.trim().toUpperCase();
    let amount;
    try { amount = parsePositiveAmount(sendAmount); }
    catch (failure) { setError(failure.message === "amount_whole_number_required" ? "Enter a whole number of NSAT." : "Enter an amount greater than zero within the per transfer limit."); return; }
    setSendBusy(true);
    try {
      const state = await walletApi.preflight(address, destination);
      if (state.network !== MAINNET || state.source !== address || state.destination !== destination) throw new Error("The Mainnet account response did not match this transfer.");
      const prepared = paymentPreflight({
        sourceAddress: address,
        destinationAddress: destination,
        amount,
        balance: state.balance,
        sequence: state.sequence,
        baseFee: state.fee,
        baseReserve: state.base_reserve,
        destinationExists: state.destination_exists,
      });
      setSendReview({ state, prepared, destination, amount: prepared.amount.toString() });
    } catch (failure) {
      const code = failure?.response?.data?.code;
      const message = code === "source_account_not_found" ? "This wallet has no funded Mainnet account yet. Receive NSAT before sending." : code === "mainnet_unverified" ? "NSAT Mainnet could not be verified. Sending is paused." : code === "invalid_destination_address" ? "Enter a valid NSAT recipient address." : failure?.message || "Could not prepare this transfer.";
      setError(message);
    } finally { setSendBusy(false); }
  };

  const checkConfirmation = async (hash, submittedAt, { poll = false, transfer = null } = {}) => {
    setTxStatus({ hash, state: "pending", submittedAt, transfer });
    const deadline = Date.now() + (poll ? 90_000 : 12_000);
    do {
      try {
        const result = await walletApi.confirmation(hash, submittedAt);
        if (result.hash !== hash) throw new Error("Confirmation hash mismatch");
        if (result.status === "confirmed" && result.success === true) {
          setTxStatus({ hash, state: "confirmed", result, transfer });
          setRefreshKey((value) => value + 1);
          if (launch?.roomId && transfer && !postedReceiptHashesRef.current.has(hash)) {
            postedReceiptHashesRef.current.add(hash);
            const receipt = createWalletReceiptMessage({ hash, address: transfer.destination, amount: transfer.amount, ledger: result.ledger ?? "" });
            void sendText(launch.roomId, receipt, null, { linkPreview: false });
          }
          return;
        }
        if (result.status === "failed" || (result.status === "confirmed" && result.success === false)) {
          setTxStatus({ hash, state: "failed", result, transfer });
          setRefreshKey((value) => value + 1);
          return;
        }
        setTxStatus({ hash, state: result.status === "pending" ? "pending" : "unknown", result, submittedAt, transfer });
        if (!poll || Date.now() >= deadline || ["unknown", "not_found"].includes(result.status)) return;
      } catch {
        setTxStatus((current) => current?.hash === hash ? { ...current, state: "unknown", submittedAt } : current);
        if (!poll || Date.now() >= deadline) return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 2_000));
    } while (Date.now() < deadline);
    setTxStatus((current) => current?.hash === hash && current.state === "pending" ? { ...current, state: "unknown", submittedAt } : current);
  };

  const submitTransfer = async () => {
    if (!sendReview || !signingSecretRef.current || !unlocked) return;
    setSendBusy(true);
    setError("");
    let signed = null;
    const submittedAt = Math.floor(Date.now() / 1000);
    try {
      const latest = await walletApi.preflight(address, sendReview.destination);
      const previous = sendReview.state;
      if (latest.network !== MAINNET || latest.source !== address || latest.destination !== sendReview.destination
        || latest.balance !== previous.balance || latest.sequence !== previous.sequence
        || latest.fee !== previous.fee || latest.base_reserve !== previous.base_reserve
        || latest.destination_exists !== previous.destination_exists) {
        setSendReview(null);
        throw new Error("Account balance, sequence, network fee, or recipient state changed. Review the transfer again.");
      }
      signed = await buildSignedPayment({ secret: signingSecretRef.current, destinationAddress: sendReview.destination, preflight: sendReview.prepared });
      const response = await walletApi.submit(signed.envelopeXdr);
      if (!["PENDING", "DUPLICATE"].includes(String(response.status || "").toUpperCase())) {
        if (response.status === "ERROR") {
          setTxStatus({ hash: signed.hash, state: "failed", detail: "The NSAT node rejected this signed transaction." });
          setSendReview(null);
          return;
        }
        setTxStatus({ hash: signed.hash, state: "unknown", submittedAt });
        setSendReview(null);
        return;
      }
      setSendReview(null);
      const transfer = { destination: sendReview.destination, amount: sendReview.amount };
      setTxStatus({ hash: signed.hash, state: "pending", submittedAt, transfer });
      void checkConfirmation(signed.hash, submittedAt, { poll: true, transfer });
    } catch (failure) {
      if (signed) {
        // A timeout after submission may be ambiguous. Never sign a replacement or rebroadcast automatically.
        setSendReview(null);
        setTxStatus({ hash: signed.hash, state: "unknown", submittedAt, transfer: { destination: sendReview.destination, amount: sendReview.amount } });
      } else setError(failure?.message || "The transfer was not signed or submitted.");
    } finally { setSendBusy(false); }
  };

  if (launch?.orderId) {
    return <MarketplaceCheckout orderId={launch.orderId} onDone={() => app.setSection("marketplace")} />;
  }

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
            <p className="wallet-native__lead">Create a device-secured wallet, restore one, or watch a public address.</p>
            {!keyFlow ? <div className="wallet-native__key-actions">
              <button type="button" className="btn btn--primary" onClick={beginCreateWallet}>Create new wallet</button>
              <button type="button" className="btn btn--secondary" onClick={() => { setKeyError(""); setKeyFlow("restore"); }}>Restore with recovery key</button>
              <button type="button" className="wallet-native__text-button" onClick={() => setKeyFlow("watch")}>View a public address</button>
            </div> : null}

            {keyFlow === "create" && pendingWallet ? <form className="wallet-native__key-form" onSubmit={submitCreateWallet}>
              <h2>Back up your recovery key</h2>
              <p>This key controls the wallet. Anyone with it can spend the funds. Save it somewhere private; it will only be shown here now.</p>
              <code className="wallet-native__recovery-key">{pendingWallet.secret}</code>
              <label className="wallet-native__check"><input type="checkbox" checked={backupConfirmed} onChange={(event) => setBackupConfirmed(event.target.checked)} /> I saved this recovery key somewhere safe.</label>
              <label>Device password<input type="password" autoComplete="new-password" minLength={10} value={walletPassword} onChange={(event) => setWalletPassword(event.target.value)} placeholder="At least 10 characters" required /></label>
              <label>Confirm password<input type="password" autoComplete="new-password" value={passwordConfirm} onChange={(event) => setPasswordConfirm(event.target.value)} required /></label>
              <div className="wallet-native__key-buttons"><button type="button" className="btn btn--secondary" onClick={() => { setKeyFlow(""); setPendingWallet(null); }}>Cancel</button><button type="submit" className="btn btn--primary" disabled={!backupConfirmed || keyBusy}>{keyBusy ? "Securing…" : "Secure wallet"}</button></div>
            </form> : null}

            {keyFlow === "restore" ? <form className="wallet-native__key-form" onSubmit={submitRestoreWallet}>
              <h2>Restore wallet</h2>
              <label>Recovery key<input value={recoveryKey} onChange={(event) => setRecoveryKey(event.target.value)} placeholder="S…" autoCapitalize="characters" autoComplete="off" spellCheck="false" required /></label>
              <label>Create device password<input type="password" autoComplete="new-password" minLength={10} value={walletPassword} onChange={(event) => setWalletPassword(event.target.value)} required /></label>
              <label>Confirm password<input type="password" autoComplete="new-password" value={passwordConfirm} onChange={(event) => setPasswordConfirm(event.target.value)} required /></label>
              <div className="wallet-native__key-buttons"><button type="button" className="btn btn--secondary" onClick={() => setKeyFlow("")}>Cancel</button><button type="submit" className="btn btn--primary" disabled={keyBusy}>{keyBusy ? "Restoring…" : "Restore wallet"}</button></div>
            </form> : null}

            {keyFlow === "unlock" ? <form className="wallet-native__key-form" onSubmit={submitUnlockWallet}>
              <h2>Unlock wallet</h2>
              <label>Device password<input type="password" autoComplete="current-password" value={walletPassword} onChange={(event) => setWalletPassword(event.target.value)} required /></label>
              <div className="wallet-native__key-buttons"><button type="button" className="btn btn--secondary" onClick={() => setKeyFlow("")}>Cancel</button><button type="submit" className="btn btn--primary" disabled={keyBusy}>{keyBusy ? "Unlocking…" : "Unlock"}</button></div>
            </form> : null}

            {keyFlow === "watch" ? <>
            <form className="wallet-native__address-form" onSubmit={saveAddress}>
              <label htmlFor="native-wallet-address">NSAT public address</label>
              <input id="native-wallet-address" value={addressInput} onChange={(event) => setAddressInput(event.target.value)} placeholder="G…" autoCapitalize="characters" autoComplete="off" spellCheck="false" />
              <button type="submit" className="btn btn--primary">View wallet</button>
            </form>
            <button type="button" className="wallet-native__text-button" onClick={() => setKeyFlow("")}>Back</button>
            <p className="wallet-native__privacy"><ShieldCheck size={16} /> This view-only mode never asks for a recovery key.</p>
            </> : null}
            {keyError ? <p className="wallet-native__error" role="alert">{keyError}</p> : null}
            {error ? <p className="wallet-native__error" role="alert">{error}</p> : null}
            <p className="wallet-native__availability">Your recovery key stays on this device. Transfers are signed locally and are public and irreversible.</p>
          </div>
        ) : (
          <>
            <div className="wallet-native__account-row">
              <div><span className="wallet-native__eyebrow">YOUR NSAT ADDRESS</span><strong title={address}>{shortAddress(address)}</strong></div>
              <button type="button" className="wallet-native__icon-button" aria-label="Copy address" onClick={copyAddress}><Copy size={17} /></button>
              {ownsWallet ? <button type="button" className="wallet-native__lock-button" onClick={() => unlocked ? lockWallet() : (setKeyError(""), setKeyFlow("unlock"))}>{unlocked ? "Lock" : "Unlock"}</button> : null}
            </div>

            <div className="wallet-native__account-link" role="status">
              <div>
                <strong>{accountLink.loading ? "Checking account connection…" : accountLink.connected ? "Wallet linked to your account" : "Wallet not linked to your account"}</strong>
                <span>{accountLink.connected && accountLink.address === address
                  ? "Marketplace purchases and chat transfers can use this verified address."
                  : accountLink.connected
                    ? `Linked address ${shortAddress(accountLink.address)} differs from this device wallet.`
                    : "Link this wallet to buy marketplace items and enable verified wallet features in chat."}</span>
                {accountLink.error ? <span className="wallet-native__link-error">{accountLink.error}</span> : null}
              </div>
              {accountLink.connected ? (
                confirmUnlink ? <div className="wallet-native__link-actions"><button type="button" className="wallet-native__text-button" onClick={() => setConfirmUnlink(false)}>Keep linked</button><button type="button" className="wallet-native__text-button is-danger" onClick={disconnectWalletFromAccount} disabled={linkBusy}>Disconnect</button></div>
                  : <button type="button" className="wallet-native__text-button" onClick={() => setConfirmUnlink(true)}>Disconnect</button>
              ) : !accountLink.connected ? (
                <button type="button" className="btn btn--secondary" onClick={connectWalletToAccount} disabled={linkBusy || accountLink.loading}>{linkBusy ? "Connecting…" : unlocked ? "Connect wallet" : "Unlock & connect"}</button>
              ) : null}
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
                {ownsWallet ? <form className="wallet-native__send-form" onSubmit={reviewSend}>
                  <label>Recipient NSAT address<input value={recipient} onChange={(event) => setRecipient(event.target.value.toUpperCase())} placeholder="G…" autoCapitalize="characters" autoComplete="off" spellCheck="false" required /></label>
                  <label>Amount (whole NSAT)<input inputMode="numeric" value={sendAmount} onChange={(event) => setSendAmount(event.target.value)} placeholder="0" required /></label>
                  {!unlocked ? <button type="button" className="btn btn--secondary" onClick={() => setKeyFlow("unlock")}>Unlock wallet to send</button> : <button type="submit" className="btn btn--primary" disabled={sendBusy}>{sendBusy ? "Checking Mainnet…" : "Review transfer"}</button>}
                </form> : <div className="wallet-native__notice"><ShieldCheck size={18} /><span>This is a view-only address. Restore or create a wallet you control to send NSAT.</span></div>}
                <p className="wallet-native__availability">The transfer is signed on this device. Before signing, NSATChat checks the Mainnet identity, live fee, latest sequence and balance, recipient address, and reserve requirement.</p>
                {error ? <p className="wallet-native__error" role="alert">{error}</p> : null}
                {sendReview ? <div className="wallet-native__review" role="dialog" aria-modal="true" aria-label="Review NSAT transfer">
                  <h3>Review transfer</h3><dl><div><dt>To</dt><dd>{sendReview.destination}</dd></div><div><dt>Amount</dt><dd>{exactAmount(sendReview.amount)} NSAT</dd></div><div><dt>Network fee</dt><dd>{exactAmount(sendReview.prepared.fee)} NSAT</dd></div><div><dt>Total debit</dt><dd>{exactAmount(sendReview.prepared.total.toString())} NSAT</dd></div><div><dt>Network</dt><dd>Verified NSAT Mainnet</dd></div>{sendReview.prepared.create ? <div><dt>Account setup</dt><dd>Create new recipient account</dd></div> : null}</dl>
                  {sendReview.prepared.create ? <p>The recipient address has no account yet. This transfer will create one and must meet the current Mainnet reserve requirement.</p> : null}
                  <p>Transfers are public and irreversible. Check the full recipient address before approving.</p>
                  <div className="wallet-native__key-buttons"><button type="button" className="btn btn--secondary" onClick={() => setSendReview(null)}>Cancel</button><button type="button" className="btn btn--primary" onClick={submitTransfer} disabled={sendBusy}>{sendBusy ? "Signing and submitting…" : "Confirm and send"}</button></div>
                </div> : null}
                {txStatus ? <div className={`wallet-native__tx-status is-${txStatus.state}`} role="status"><strong>{txStatus.state === "confirmed" ? "Confirmed on Mainnet" : txStatus.state === "failed" ? "Transfer failed" : txStatus.state === "pending" ? "Waiting for Mainnet confirmation…" : "Status unknown — do not send again yet"}</strong><code>{txStatus.hash}</code>{txStatus.result?.ledger ? <span>Ledger #{txStatus.result.ledger}</span> : null}{txStatus.result?.result_code ? <span>{txStatus.result.result_code}</span> : null}{["unknown", "pending"].includes(txStatus.state) ? <button type="button" className="wallet-native__text-button" onClick={() => checkConfirmation(txStatus.hash, txStatus.submittedAt, { transfer: txStatus.transfer })}>Check status</button> : null}</div> : null}
              </section>
            ) : null}

            {keyFlow === "unlock" ? <form className="wallet-native__inline-unlock" onSubmit={submitUnlockWallet}><label>Device password<input type="password" autoComplete="current-password" value={walletPassword} onChange={(event) => setWalletPassword(event.target.value)} required /></label><button type="submit" className="btn btn--primary" disabled={keyBusy}>{keyBusy ? "Unlocking…" : "Unlock"}</button>{keyError ? <p className="wallet-native__error" role="alert">{keyError}</p> : null}</form> : null}
            {ownsWallet ? <button type="button" className="wallet-native__change" onClick={lockWallet}>Lock this device wallet</button> : <button type="button" className="wallet-native__change" onClick={() => { try { window.localStorage.removeItem(ADDRESS_KEY); } catch { /* ignore */ } setAddress(""); setWallet(null); setQr(""); setSection("overview"); }}>Change or clear viewed address</button>}
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
