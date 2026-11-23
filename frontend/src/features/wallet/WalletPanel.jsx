import { useCallback, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, ExternalLink, Eye, RefreshCw, WalletCards } from "lucide-react";
import { walletApi } from "./api";
import { PanelHeader } from "../../components/common/ui";

const STORAGE_KEY = "satoshicore.wallet.watch-address.v1";
const ADDRESS_RE = /^G[A-Z2-7]{55}$/;
const EXPLORER = "https://wallet.satoshicore.org/explorer/?q=";

function readSavedAddress() {
  try {
    const value = localStorage.getItem(STORAGE_KEY) || "";
    return ADDRESS_RE.test(value) ? value : "";
  } catch {
    return "";
  }
}

function formatInteger(value) {
  const text = String(value ?? "");
  return /^\d+$/.test(text) ? text.replace(/\B(?=(\d{3})+(?!\d))/g, ",") : "—";
}

function shortAddress(address) {
  return address ? `${address.slice(0, 10)}…${address.slice(-8)}` : "";
}

function formatDate(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value <= 0) return "Time unavailable";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value * 1000));
}

function messageForError(error) {
  const code = error?.response?.data?.code;
  if (code === "invalid_address") return "Enter a valid NSAT public address starting with G.";
  if (code === "mainnet_unverified") return "The NSAT Mainnet identity could not be verified. Wallet data is hidden for safety.";
  if (code === "wallet_unavailable" || error?.response?.status === 503) return "NSAT Mainnet data is temporarily unavailable. Try again shortly.";
  return "Could not load wallet data. Check your connection and try again.";
}

export default function WalletPanel() {
  const [address, setAddress] = useState(readSavedAddress);
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const load = useCallback(async (candidate) => {
    const normalized = String(candidate || "").trim().toUpperCase();
    setAddress(normalized);
    setSnapshot(null);
    setError("");
    setCopied(false);
    if (!ADDRESS_RE.test(normalized)) {
      setError("Enter a valid NSAT public address starting with G.");
      return;
    }
    try { localStorage.setItem(STORAGE_KEY, normalized); } catch { /* optional device preference */ }
    setLoading(true);
    try {
      setSnapshot(await walletApi.read(normalized));
    } catch (requestError) {
      setError(messageForError(requestError));
    } finally {
      setLoading(false);
    }
  }, []);

  const clear = () => {
    try { localStorage.removeItem(STORAGE_KEY); } catch { /* optional device preference */ }
    setAddress("");
    setSnapshot(null);
    setError("");
  };

  const copyAddress = async () => {
    if (!snapshot?.address) return;
    try {
      await navigator.clipboard.writeText(snapshot.address);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("Clipboard access is unavailable in this browser.");
    }
  };

  const active = snapshot?.account_status === "active";
  const history = Array.isArray(snapshot?.history) ? snapshot.history : [];

  return (
    <section className="panel wallet-panel">
      <PanelHeader title="Wallet" />
      <div className="panel__scroll wallet-panel__scroll">
        <div className="wallet-hero">
          <span className="wallet-hero__icon"><WalletCards size={25} /></span>
          <div>
            <h2>NSAT Wallet</h2>
            <span className="wallet-hero__tag"><Eye size={14} /> View only · NSAT Mainnet</span>
          </div>
        </div>

        <div className="wallet-address-form">
          <label htmlFor="wallet-watch-address">Public wallet address</label>
          <form onSubmit={(event) => { event.preventDefault(); load(address); }}>
            <input
              id="wallet-watch-address"
              value={address}
              onChange={(event) => setAddress(event.target.value.toUpperCase())}
              autoCapitalize="characters"
              autoComplete="off"
              autoCorrect="off"
              spellCheck="false"
              placeholder="G…"
              aria-describedby="wallet-address-help"
            />
            <button className="btn btn--primary" type="submit" disabled={loading}>
              {loading ? <RefreshCw size={17} className="wallet-spin" /> : "View"}
            </button>
          </form>
          <p id="wallet-address-help">Paste a public address from your NSAT Wallet. This does not connect signing keys.</p>
        </div>

        <div className="wallet-privacy-note">
          The address is saved only on this device and sent to SatoshiCore Messenger to read public Mainnet data. No private key or seed phrase is requested or stored. This screen cannot send NSAT.
        </div>

        {error ? <div className="wallet-error" role="alert">{error}</div> : null}
        {loading ? <div className="wallet-state">Checking the NSAT Mainnet…</div> : null}

        {snapshot ? (
          <>
            {active ? (
              <section className="wallet-balance-card" aria-label="NSAT balance">
                <span className="wallet-balance-card__label">On-chain balance</span>
                <strong>{formatInteger(snapshot.balance)} <small>NSAT</small></strong>
                <div className="wallet-balance-card__address">
                  <span title={snapshot.address}>{shortAddress(snapshot.address)}</span>
                  <button type="button" className="wallet-text-button" onClick={copyAddress}>{copied ? "Copied" : "Copy address"}</button>
                  <button type="button" className="wallet-text-button wallet-text-button--danger" onClick={clear}>Remove</button>
                </div>
                <span className="wallet-balance-card__ledger">Mainnet snapshot · ledger {formatInteger(snapshot.ledger)}</span>
              </section>
            ) : (
              <section className="wallet-empty-card">
                <strong>No account found on NSAT Mainnet</strong>
                <span>This address has no active on-chain account yet. No zero balance is inferred.</span>
                <button type="button" className="wallet-text-button" onClick={clear}>Remove address</button>
              </section>
            )}

            {active ? (
              <section className="wallet-history">
                <div className="wallet-history__header">
                  <h3>Recent activity</h3>
                  {snapshot.indexed_head ? <span>Indexed through {formatInteger(snapshot.indexed_head)}</span> : null}
                </div>
                {snapshot.history_status !== "available" ? (
                  <div className="wallet-state wallet-state--inline">Balance is live, but indexed transaction history is temporarily unavailable.</div>
                ) : history.length ? (
                  <div className="wallet-tx-list">
                    {history.map((item) => {
                      const outgoing = item.direction === "out";
                      const sign = item.direction === "self" ? "" : outgoing ? "−" : "+";
                      const signedAmount = `${sign}${formatInteger(item.amount)}`;
                      return (
                        <a className="wallet-tx" href={`${EXPLORER}${encodeURIComponent(item.hash)}`} target="_blank" rel="noreferrer" key={item.hash}>
                          <span className={`wallet-tx__icon ${outgoing ? "is-out" : "is-in"}`}>{outgoing ? <ArrowUpRight size={18} /> : <ArrowDownLeft size={18} />}</span>
                          <span className="wallet-tx__body">
                            <strong>{outgoing ? "Sent" : item.direction === "self" ? "Self transfer" : "Received"} · {item.success ? "Confirmed" : "Failed"}</strong>
                            <span>{formatDate(item.close_time)} · ledger {formatInteger(item.ledger)}</span>
                            <span className="wallet-tx__address">{item.counterparty ? shortAddress(item.counterparty) : item.kind}</span>
                          </span>
                          <span className={`wallet-tx__amount ${outgoing ? "is-out" : "is-in"}`}>{signedAmount}<small>NSAT</small></span>
                          <ExternalLink size={14} className="wallet-tx__external" />
                        </a>
                      );
                    })}
                  </div>
                ) : (
                  <div className="wallet-state wallet-state--inline">No indexed transactions were found for this address.</div>
                )}
              </section>
            ) : null}
          </>
        ) : null}

        <a className="wallet-open-link" href="https://wallet.satoshicore.org/" target="_blank" rel="noreferrer">
          Open SatoshiCore Wallet <ExternalLink size={16} />
        </a>
        <p className="wallet-footer-note">Wallet creation, recovery, receiving tools and transaction signing remain on the secure Wallet site. Verify network details there before approving any transaction.</p>
      </div>
    </section>
  );
}
