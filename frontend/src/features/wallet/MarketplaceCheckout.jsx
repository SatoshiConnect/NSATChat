import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, Copy, RefreshCw, ShieldCheck } from "lucide-react";
import { errorMessage } from "../../api/client";
import { marketplaceApi } from "../../api/endpoints";
import { toast } from "../../services/toast";
import { unlockEncryptedWallet } from "./keystore";
import { walletApi } from "./api";
import { NSAT_BASE_FEE_POLICY, buildSignedPayment, paymentPreflight } from "./transaction";
import { formatNsat, transferRequirement, transferShortfall } from "./checkoutMath";
import { checkoutRecipientMessage, inspectCheckoutRecipients } from "./checkoutReadiness";

const ADDRESS_RE = /^G[A-Z2-7]{55}$/;
const ROLE_LABEL = { creator: "Creator share", platform: "Platform fee" };
const NETWORK_FEE_NSAT = Number(NSAT_BASE_FEE_POLICY);

function amountLabel(value) {
  try {
    return BigInt(value).toLocaleString("en-US");
  } catch {
    return "—";
  }
}

/**
 * Paid checkout for a marketplace order. The buyer's key never leaves this
 * component: each tranche is signed here and only the signed envelope is sent,
 * and access is shown only after the indexer confirms the payment.
 */
export default function MarketplaceCheckout({ orderId, onDone }) {
  const [order, setOrder] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  const [recipientReadiness, setRecipientReadiness] = useState(null);
  const secretRef = useRef("");

  const recipientCheckKey = order
    ? JSON.stringify([
      order.buyer_address,
      (order.payments || [])
        .filter((payment) => payment.state !== "confirmed")
        .map(({ role, amount_nsat, payee_address }) => [role, amount_nsat, payee_address]),
    ])
    : "";

  const load = async () => {
    try {
      const fresh = await marketplaceApi.order(orderId);
      setOrder(fresh);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    marketplaceApi.order(orderId)
      .then((fresh) => { if (active) setOrder(fresh); })
      .catch((failure) => { if (active) setError(errorMessage(failure)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; secretRef.current = ""; };
  }, [orderId]);

  useEffect(() => {
    // The inbox socket can confirm the order before the poll catches up.
    const onPaid = (event) => {
      if (event.detail?.order_id !== orderId) return;
      marketplaceApi.order(orderId).then(setOrder).catch(() => {});
    };
    window.addEventListener("mhtalk:marketplace-order-paid", onPaid);
    return () => window.removeEventListener("mhtalk:marketplace-order-paid", onPaid);
  }, [orderId]);

  useEffect(() => {
    if (!order || order.state !== "partially_paid") return undefined;
    const timer = window.setInterval(() => { load(); }, 8_000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order?.state, orderId]);

  useEffect(() => {
    if (!order || !recipientCheckKey || order.state === "paid" || ["expired", "failed"].includes(order.state)) return undefined;
    let active = true;
    inspectCheckoutRecipients(order, (source, destination) => walletApi.preflight(source, destination))
      .then((issue) => {
        if (active) setRecipientReadiness({ key: recipientCheckKey, state: issue ? "blocked" : "ready", issue });
      })
      .catch(() => {
        if (active) setRecipientReadiness({ key: recipientCheckKey, state: "unavailable" });
      });
    return () => { active = false; };
  }, [order, recipientCheckKey]);

  const unlock = async (event) => {
    event.preventDefault();
    setError("");
    try {
      const wallet = await unlockEncryptedWallet(password);
      if (wallet.address !== order?.buyer_address) throw new Error("wallet_address_mismatch");
      secretRef.current = wallet.secret;
      setPassword("");
      toast.success("Wallet unlocked for this payment.");
      return wallet;
    } catch (failure) {
      const code = failure?.message || "";
      setError(
        code === "wallet_address_mismatch"
          ? "This device holds a different wallet than the one linked to your account. Reconnect that wallet first."
          : "That password did not unlock your wallet.",
      );
      return null;
    }
  };

  const copyAddress = async (address) => {
    try {
      await navigator.clipboard.writeText(address);
      toast.success("Payee address copied.");
    } catch {
      toast.error("Could not copy the address. Select it instead.");
    }
  };

  const pay = async (event) => {
    if (event?.preventDefault) event.preventDefault();
    if (!order) return;
    setError("");
    // Re-check live recipient account state before asking for the buyer's
    // password. The price is server-defined; never inflate it to activate a
    // seller account automatically.
    try {
      const recipientIssue = await inspectCheckoutRecipients(
        order,
        (source, destination) => walletApi.preflight(source, destination),
      );
      if (recipientIssue) {
        setRecipientReadiness({ key: recipientCheckKey, state: "blocked", issue: recipientIssue });
        setError(checkoutRecipientMessage(recipientIssue, ROLE_LABEL[recipientIssue.role] || recipientIssue.role));
        return;
      }
      setRecipientReadiness({ key: recipientCheckKey, state: "ready" });
    } catch {
      setRecipientReadiness({ key: recipientCheckKey, state: "unavailable" });
      setError("Could not verify the recipient wallet on NSAT Mainnet. Refresh the order and try again. No payment was sent.");
      return;
    }
    let secret = secretRef.current;
    if (!secret) {
      const wallet = await unlock(event);
      if (!wallet) return;
      secret = wallet.secret;
    }
    setBusy(true);
    let latest = order;
    // Filled from the live Mainnet account before each signature, so a balance
    // refusal can state the exact deficit instead of a generic failure.
    let shortfall = 0n;
    let requirement = 0n;
    let available = "0";
    let payingLabel = "";
    try {
      for (const payment of order.payments || []) {
        if (payment.state === "confirmed") continue;
        if (!ADDRESS_RE.test(payment.payee_address)) throw new Error("invalid_payee");
        payingLabel = ROLE_LABEL[payment.role] || payment.role;
        setStage(`Signing ${payingLabel}…`);
        const facts = await walletApi.preflight(order.buyer_address, payment.payee_address);
        available = facts.balance;
        try {
          requirement = transferRequirement({
            amount: payment.amount_nsat,
            fee: facts.fee,
            reserve: facts.base_reserve,
          });
          shortfall = transferShortfall({
            amount: payment.amount_nsat,
            balance: facts.balance,
            fee: facts.fee,
            reserve: facts.base_reserve,
          });
        } catch {
          // Malformed account facts are paymentPreflight's call to refuse; the
          // pre-sign arithmetic must never block it with a different error.
          requirement = 0n;
          shortfall = 0n;
        }
        const preflight = paymentPreflight({
          sourceAddress: order.buyer_address,
          destinationAddress: payment.payee_address,
          amount: payment.amount_nsat,
          balance: facts.balance,
          sequence: facts.sequence,
          baseFee: facts.fee,
          baseReserve: facts.base_reserve,
          destinationExists: facts.destination_exists,
        });
        const signed = await buildSignedPayment({
          secret,
          destinationAddress: payment.payee_address,
          preflight,
        });
        if (signed.sourceAddress !== order.buyer_address) throw new Error("wallet_address_mismatch");
        setStage("Submitting signed payment…");
        latest = await marketplaceApi.payOrder(order.id, payment.role, signed.envelopeXdr);
        setOrder(latest);
      }
      if (latest.state === "paid") {
        toast.success(latest.gift ? `Paid. ${latest.gift.recipient_name} received the gift.` : "Paid. Your item is unlocked.");
        onDone?.();
        return;
      }
      setStage("Waiting for the NSAT network to confirm…");
      for (let attempt = 0; attempt < 12; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 5_000));
        latest = await marketplaceApi.order(order.id);
        setOrder(latest);
        if (latest.state === "paid") {
          toast.success(
            latest.gift
              ? `Payment confirmed. ${latest.gift.recipient_name} received the gift.`
              : "Payment confirmed. Your item is unlocked.",
          );
          onDone?.();
          return;
        }
        if (latest.state === "failed") throw new Error("payment_failed");
      }
      toast("The network is still confirming. Reopen this order in a moment.");
    } catch (failure) {
      const code = failure?.response?.data?.code || failure?.message || "";
      const messages = {
        envelope_amount_mismatch: "The signed amount did not match this order.",
        envelope_payee_mismatch: "The signed payment went to the wrong address.",
        envelope_source_mismatch: "Sign in with the wallet linked to your account.",
        insufficient_balance_or_reserve: "Your wallet balance cannot cover this payment.",
        destination_creation_reserve_too_low: "The recipient wallet is not activated. The listed price was not changed and no payment was sent.",
        payment_already_submitted: "This part of the order is already submitted.",
        order_expired: "This order expired. Start checkout again.",
        already_owned: "You already own this item through another order. Nothing was charged.",
        order_closed: "This order is closed. Start checkout again from the catalog.",
        payment_failed: "The network rejected the payment. Nothing was delivered.",
        wallet_address_mismatch: "This device holds a different wallet than your account.",
      };
      if (code === "insufficient_balance_or_reserve" && shortfall > 0n) {
        setError(
          `This wallet holds ${formatNsat(available)} NSAT. The ${payingLabel || "payment"} transfer needs `
          + `${formatNsat(requirement)} NSAT (amount + ${NETWORK_FEE_NSAT} NSAT network fee + the account reserve), `
          + `so it is ${formatNsat(shortfall)} NSAT short. Add NSAT and try again.`,
        );
      } else {
        setError(messages[code] || errorMessage(failure));
      }
    } finally {
      setBusy(false);
      setStage("");
    }
  };

  if (loading) return <div className="wallet-native__empty">Loading order…</div>;
  if (!order) return <div className="wallet-native__empty">{error || "Order unavailable."}</div>;

  const pending = (order.payments || []).filter((payment) => payment.state !== "confirmed");
  const paid = order.state === "paid";
  const closed = ["expired", "failed"].includes(order.state);
  const networkFees = pending.length * NETWORK_FEE_NSAT;
  const readinessState = recipientReadiness?.key === recipientCheckKey ? recipientReadiness.state : "checking";

  return (
    <section className="wallet-native">
      <header className="wallet-native__header">
        <button type="button" className="wallet-native__back" onClick={() => onDone?.()} aria-label="Back"><ArrowLeft size={18} /></button>
        <div className="wallet-native__brand"><ShieldCheck size={19} /><strong>{paid ? "Purchase complete" : "Checkout"}</strong><span>{order.item.title}</span></div>
        <button type="button" className="wallet-native__refresh" onClick={() => load()} aria-label="Refresh order status"><RefreshCw size={18} /></button>
      </header>

      <div className="wallet-native__body">
        <div className="wallet-checkout">
          <div className="wallet-checkout__card">
            <div className="wallet-checkout__row"><span>Item</span><strong>{order.item.title}</strong></div>
            {order.gift ? <div className="wallet-checkout__row"><span>Gift for</span><strong>{order.gift.recipient_name}</strong></div> : null}
            <div className="wallet-checkout__row"><span>Price</span><strong>{amountLabel(order.unit_amount_nsat)} NSAT</strong></div>
            {order.platform_fee_nsat ? <div className="wallet-checkout__row"><span>Platform fee</span><strong>{amountLabel(order.platform_fee_nsat)} NSAT</strong></div> : null}
            <div className="wallet-checkout__row"><span>Creator receives</span><strong>{amountLabel(order.creator_proceeds_nsat)} NSAT</strong></div>
            {pending.length ? <div className="wallet-checkout__row"><span>Network fee</span><strong>{networkFees} NSAT</strong></div> : null}
          </div>

          <div className="wallet-checkout__card">
            {(order.payments || []).map((payment) => (
              <div className="wallet-checkout__payment" key={payment.role}>
                <div className="wallet-checkout__row">
                  <span>{ROLE_LABEL[payment.role] || payment.role}</span>
                  <strong>{amountLabel(payment.amount_nsat)} NSAT · {payment.state}</strong>
                </div>
                <div className="wallet-checkout__payee">
                  <code title={payment.payee_address}>{payment.payee_address}</code>
                  <button type="button" onClick={() => copyAddress(payment.payee_address)} aria-label={`Copy ${ROLE_LABEL[payment.role] || payment.role} address`}><Copy size={13} /></button>
                </div>
                {payment.tx_hash ? <small className="wallet-checkout__hash">Transaction {payment.tx_hash.slice(0, 16)}…</small> : null}
              </div>
            ))}
            <div className="wallet-checkout__row"><span>Status</span><strong>{order.state.replace("_", " ")}</strong></div>
            {!paid && !closed ? <div className="wallet-checkout__row"><span>Order expires in</span><strong>{Math.ceil(order.seconds_remaining / 60)} min</strong></div> : null}
          </div>

          {paid ? (
            <p className="wallet-checkout__hint">
              <Check size={16} />
              {order.gift
                ? ` The creator was paid on NSAT Mainnet and the gift is in ${order.gift.recipient_name}'s library.`
                : " The creator was paid on NSAT Mainnet and the item is in your library."}
            </p>
          ) : closed ? (
            <p className="wallet-native__error">This order is {order.state}. Start a new checkout from the marketplace.</p>
          ) : (
            <>
              {readinessState === "checking" ? (
                <p className="wallet-checkout__hint">Checking recipient wallets on NSAT Mainnet before enabling payment…</p>
              ) : null}
              {readinessState === "blocked" ? (
                <div className="wallet-native__error" role="alert">
                  {checkoutRecipientMessage(recipientReadiness.issue, ROLE_LABEL[recipientReadiness.issue.role] || recipientReadiness.issue.role)}
                </div>
              ) : null}
              {readinessState === "unavailable" ? (
                <div className="wallet-native__error" role="alert">
                  Recipient wallet status could not be verified. Payment is disabled until NSAT Mainnet can confirm it. No payment has been sent.
                  <button type="button" className="wallet-native__refresh" onClick={() => load()}>Retry</button>
                </div>
              ) : null}
              <form className="wallet-native__key-form" onSubmit={pay}>
              <h2>Pay {amountLabel(order.total_due_nsat)} NSAT</h2>
              {readinessState === "ready" ? <>
                <label>Wallet password
                  <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Unlock to sign" autoComplete="current-password" />
                </label>
                <p className="wallet-checkout__hint"><ShieldCheck size={16} /> Signed on this device. NSATChat never sends your key.</p>
                <p className="wallet-checkout__disclosure">
                  Payment is final: NSAT transfers cannot be reversed or refunded by NSATChat. A {NETWORK_FEE_NSAT} NSAT
                  network fee applies to each of the {pending.length} transfer(s), and the rest is paid directly to the creator.
                </p>
              </> : null}
              {error ? <p className="wallet-native__error">{error}</p> : null}
              {stage ? <p className="wallet-checkout__hint">{stage}</p> : null}
              {readinessState === "ready" ? (
                <button type="submit" className="btn btn--primary" disabled={busy}>{busy ? "Processing…" : "Sign and pay"}</button>
              ) : null}
              </form>
            </>
          )}
          {error && (paid || closed) ? <p className="wallet-native__error">{error}</p> : null}
        </div>
      </div>
    </section>
  );
}
