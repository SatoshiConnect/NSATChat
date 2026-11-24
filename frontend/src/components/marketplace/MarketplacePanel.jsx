import { useCallback, useEffect, useRef, useState } from "react";
import { Gift, Library, Search, Sparkles, Store, Upload } from "lucide-react";
import { errorMessage } from "../../api/client";
import { marketplaceApi } from "../../api/endpoints";
import { toast } from "../../services/toast";
import { useApp } from "../layout/AppContext";
import { EmptyState, PanelHeader, Spinner } from "../common/ui";

const CATEGORIES = ["all", "gift", "sticker_pack", "profile_frame", "badge", "theme", "avatar", "pixel_world"];
const PURCHASE_ERRORS = {
  wallet_not_linked: "Connect your NSAT wallet in the Wallet tab before buying.",
  creator_wallet_unavailable: "This creator has not connected an NSAT wallet yet.",
  already_owned: "You already own this item.",
  order_already_open: "You already have an open order for this item. Continue it from the banner at the top of Explore.",
  cannot_buy_own_item: "This is your own listing.",
  marketplace_payments_unavailable: "Marketplace payments are paused right now.",
  item_not_for_sale: "This listing has no sale price, so there is nothing to pay.",
  item_unavailable: "This listing is no longer for sale.",
  marketplace_misconfigured: "Checkout is paused while the marketplace is being configured.",
};
const OPEN_ORDER_STATES = ["awaiting_payment", "partially_paid"];
const LABELS = { all: "Explore", gift: "Gifts", sticker_pack: "Stickers", profile_frame: "Frames", badge: "Badges", theme: "Themes", avatar: "Avatar", pixel_world: "Pixel World" };

export default function MarketplacePanel() {
  const app = useApp();
  const [tab, setTab] = useState("catalog");
  const [kind, setKind] = useState("all");
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState([]);
  const [library, setLibrary] = useState([]);
  const [purchases, setPurchases] = useState([]);
  const [orders, setOrders] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [creators, setCreators] = useState([]);
  const [giftHistory, setGiftHistory] = useState({ received: [], sent: [] });
  const [busy, setBusy] = useState(true);
  const [nextCursor, setNextCursor] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  const [acting, setActing] = useState(null);
  const [submissionKind, setSubmissionKind] = useState("gift");
  const purchaseKeys = useRef(new Map());
  const openOrder = orders.find((order) => OPEN_ORDER_STATES.includes(order.state));
  const giftRows = [
    ...(giftHistory.received || []).map((gift) => ({ ...gift, direction: "Received" })),
    ...(giftHistory.sent || []).map((gift) => ({ ...gift, direction: "Sent" })),
  ].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  const catalogParams = useCallback(
    () => ({ ...(kind !== "all" ? { kind } : {}), ...(query.trim() ? { q: query.trim() } : {}) }),
    [kind, query],
  );

  const refresh = useCallback(async () => {
    try {
      const [page, inventory, history, entitlements, orderHistory] = await Promise.all([
        marketplaceApi.catalogPage(catalogParams()),
        marketplaceApi.inventory(),
        marketplaceApi.purchases(),
        marketplaceApi.entitlements(),
        marketplaceApi.orders(),
      ]);
      setRows(page.items);
      setNextCursor(page.nextCursor);
      setOrders(orderHistory);
      setLibrary([
        ...entitlements.map((entry) => ({ id: `entitlement-${entry.id}`, item: entry.item, acquired_at: entry.acquired_at, on_chain: true })),
        ...inventory,
      ]);
      setPurchases(history);
      if (tab === "creator") setDashboard(await marketplaceApi.creatorDashboard());
      if (tab === "creator") setGiftHistory(await marketplaceApi.gifts());
      if (tab === "creators") setCreators(await marketplaceApi.creators());
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }, [catalogParams, tab]);

  useEffect(() => {
    let active = true;
    Promise.all([
      marketplaceApi.catalogPage(catalogParams()),
      marketplaceApi.inventory(),
      marketplaceApi.purchases(),
      marketplaceApi.entitlements(),
      marketplaceApi.orders(),
    ]).then(async ([page, inventory, history, entitlements, orderHistory]) => {
      const creatorData = tab === "creator" ? await marketplaceApi.creatorDashboard() : null;
      const creatorRows = tab === "creators" ? await marketplaceApi.creators() : null;
      const gifts = tab === "creator" ? await marketplaceApi.gifts() : null;
      if (!active) return;
      setRows(page.items);
      setNextCursor(page.nextCursor);
      setLibrary([
        ...entitlements.map((entry) => ({ id: `entitlement-${entry.id}`, item: entry.item, acquired_at: entry.acquired_at, on_chain: true })),
        ...inventory,
      ]);
      setPurchases(history);
      setOrders(orderHistory);
      if (creatorData) setDashboard(creatorData);
      if (creatorRows) setCreators(creatorRows);
      if (gifts) setGiftHistory(gifts);
    }).catch((error) => {
      if (active) toast.error(errorMessage(error));
    }).finally(() => {
      if (active) setBusy(false);
    });
    return () => { active = false; };
  }, [catalogParams, tab]);

  const loadMore = async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await marketplaceApi.catalogPage({ ...catalogParams(), cursor: nextCursor });
      // Cursor pages never overlap, but a listing can be edited between two
      // requests; keep the newest copy of each row once.
      setRows((current) => {
        const seen = new Set(current.map((item) => item.id));
        return [...current, ...page.items.filter((item) => !seen.has(item.id))];
      });
      setNextCursor(page.nextCursor);
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    // A confirmed payment may arrive while checkout is closed; the inbox
    // socket nudges this screen so the library unlocks without a reload.
    const unlock = () => { void refresh(); };
    window.addEventListener("mhtalk:marketplace-order-paid", unlock);
    return () => window.removeEventListener("mhtalk:marketplace-order-paid", unlock);
  }, [refresh]);

  const simulate = async (item) => {
    setActing(item.id);
    try {
      if (!purchaseKeys.current.has(item.id)) purchaseKeys.current.set(item.id, crypto.randomUUID());
      const result = await marketplaceApi.simulatePurchase(item.id, purchaseKeys.current.get(item.id));
      purchaseKeys.current.delete(item.id);
      toast.success(result.message || "Simulation recorded. No NSAT moved.");
      await refresh();
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setActing(null); }
  };

  const purchase = async (item) => {
    if (item.purchase_mode === "simulation") return simulate(item);
    if (item.purchase_mode !== "nsat") return undefined;
    setActing(item.id);
    try {
      if (!purchaseKeys.current.has(item.id)) purchaseKeys.current.set(item.id, crypto.randomUUID());
      const order = await marketplaceApi.createOrder(item.id, purchaseKeys.current.get(item.id));
      purchaseKeys.current.delete(item.id);
      app.openWallet({ orderId: order.id });
    } catch (error) {
      const code = error?.response?.data?.code;
      toast.error(PURCHASE_ERRORS[code] || errorMessage(error));
      // An order that is already open is payable from the pinned banner, so
      // reload the order list instead of leaving the buyer to hunt for it.
      if (code === "order_already_open") await refresh();
    } finally {
      setActing(null);
    }
    return undefined;
  };

  const submit = async (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const data = new FormData(formElement);
    const preview = data.get("preview");
    setActing("submit");
    try {
      await marketplaceApi.submit({ kind: data.get("kind"), title: data.get("title"), description: data.get("description"), proposed_price_nsat: data.get("price"), usage_rights: data.get("rights"), preview: preview?.size ? preview : undefined, assets: submissionKind === "sticker_pack" ? data.getAll("assets").filter((file) => file.size) : undefined });
      formElement.reset();
      toast.success("Submitted for moderation. It will appear after approval.");
      await refresh();
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setActing(null); }
  };

  const saveCreatorProfile = async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const profile = await marketplaceApi.updateCreatorProfile({ display_name: data.get("creator_name"), bio: data.get("creator_bio") });
      setDashboard((current) => ({ ...current, profile }));
      toast.success("Creator profile saved.");
    } catch (error) { toast.error(errorMessage(error)); }
  };

  const submitDispute = async (event, purchase) => {
    event.preventDefault();
    const reason = new FormData(event.currentTarget).get("reason");
    try {
      const result = await marketplaceApi.dispute(purchase.id, reason);
      toast.success(`Simulation dispute recorded: ${result.state}. No payment was made.`);
      await refresh();
    } catch (error) { toast.error(errorMessage(error)); }
  };

  const reportItem = async (event, item) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const data = new FormData(formElement);
    try {
      const result = await marketplaceApi.report(item.id, data.get("reason"), data.get("details"));
      toast.success(`Report received (${result.state}).`);
      formElement.reset();
    } catch (error) { toast.error(errorMessage(error)); }
  };

  return (
    <section className="panel marketplace-panel">
      <PanelHeader title="Creator marketplace" />
      <div className="marketplace__scroll">
        <div className="marketplace__hero">
          <span className="marketplace__eyebrow"><Sparkles size={15} /> SATOSHICORE CREATORS</span>
          <h1>Discover digital items</h1>
          <p>Gifts, stickers and creator collections for your SatoshiCore profile.</p>
          <div className="marketplace__notice">Prices in NSAT · Items unlock only after an on-chain payment is confirmed</div>
        </div>

        <div className="marketplace__tabs" role="tablist" aria-label="Marketplace sections">
          <button type="button" className={tab === "catalog" ? "is-active" : ""} onClick={() => setTab("catalog")}><Store size={17} /> Explore</button>
          <button type="button" className={tab === "creators" ? "is-active" : ""} onClick={() => setTab("creators")}><Sparkles size={17} /> Creators</button>
          <button type="button" className={tab === "library" ? "is-active" : ""} onClick={() => setTab("library")}><Library size={17} /> My library ({library.length})</button>
          <button type="button" className={tab === "creator" ? "is-active" : ""} onClick={() => setTab("creator")}><Upload size={17} /> Creator studio</button>
        </div>

        {tab === "catalog" ? <>
          {openOrder ? <div className="marketplace__open-order" role="status">
            <div>
              <strong>You have an open order for {openOrder.item.title}</strong>
              <span>{Number(openOrder.total_due_nsat).toLocaleString()} NSAT · {openOrder.state === "partially_paid" ? "partly paid" : "waiting for payment"}</span>
            </div>
            <button type="button" onClick={() => app.openWallet({ orderId: openOrder.id })}>Continue payment</button>
          </div> : null}
          <label className="marketplace__search"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search items" aria-label="Search marketplace items" /></label>
          <div className="marketplace__categories">{CATEGORIES.map((value) => <button type="button" key={value} className={kind === value ? "is-active" : ""} onClick={() => setKind(value)}>{LABELS[value]}</button>)}</div>
          {busy ? <div className="marketplace__loading"><Spinner /></div> : rows.length ? <div className="marketplace__grid">{rows.map((item) => (
            <article className="market-item" key={item.id}>
              {item.preview ? <img src={item.preview} alt="" className="market-item__preview" /> : <div className={`market-item__preview market-item__placeholder kind-${item.kind}`}>{item.kind === "gift" ? <Gift /> : <Sparkles />}</div>}
              <div className="market-item__body"><span className="market-item__kind">{LABELS[item.kind] || item.kind}</span><h2>{item.title}</h2><p>{item.description}</p><small>By {item.creator_name}</small><div className="market-item__foot"><strong>{item.price_label}</strong><button type="button" disabled={acting === item.id || item.purchase_mode === "closed" || item.purchase_mode === "owned"} onClick={() => purchase(item)}>{acting === item.id ? "Working…" : item.purchase_mode === "nsat" ? "Buy with NSAT" : item.purchase_mode === "simulation" ? "Try simulation" : item.purchase_mode === "owned" ? "In library" : "Not for sale"}</button></div><details className="market-item__report"><summary>Report item</summary><form onSubmit={(event) => reportItem(event, item)}><select name="reason" defaultValue="copyright"><option value="copyright">Copyright</option><option value="unsafe">Unsafe</option><option value="spam">Spam</option><option value="other">Other</option></select><input name="details" maxLength="1000" placeholder="Details (optional)" /><button type="submit">Send report</button></form></details></div>
            </article>
          ))}</div> : <EmptyState icon={Store} text="No approved items yet" />}
          {!busy && nextCursor ? <div className="marketplace__more"><button type="button" onClick={loadMore} disabled={loadingMore}>{loadingMore ? "Loading…" : "Load more"}</button></div> : null}
        </> : null}

        {tab === "creators" ? (busy ? <div className="marketplace__loading"><Spinner /></div> : creators.length ? <div className="marketplace__creator-directory">{creators.map((creator) => <article key={creator.user_id}><span className="marketplace__creator-avatar">{creator.display_name.slice(0, 1).toUpperCase()}</span><div><h2>{creator.display_name}</h2><p>{creator.bio}</p><div className="marketplace__creator-items">{creator.approved_items.map((item) => <span key={item.id}>{item.title}</span>)}</div></div></article>)}</div> : <EmptyState icon={Sparkles} text="Creator collections will appear here after items are approved." />) : null}

        {tab === "library" ? <>
          {busy ? <div className="marketplace__loading"><Spinner /></div> : library.length ? <div className="marketplace__grid">{library.map(({ id, item, acquired_at, on_chain }) => <article className="market-item market-item--library" key={id}><div className="market-item__preview market-item__placeholder"><Library /></div><div className="market-item__body"><span className="market-item__kind">{LABELS[item.kind] || item.kind}</span><h2>{item.title}</h2><p>{item.usage_rights || "Personal in-app use."}</p><small>Added {new Date(acquired_at).toLocaleDateString()}</small><strong className="market-item__owned">{on_chain ? "Owned · on-chain" : "Owned · simulated"}</strong></div></article>)}</div> : <EmptyState icon={Library} text="Your library is empty. Buy an item from the catalog to unlock it." />}
          <section className="marketplace__purchase-history"><h2>NSAT orders</h2>{orders.length ? orders.map((order) => <div className="marketplace__submission" key={order.id}><div><strong>{order.item.title}</strong><span className="marketplace__history-meta">{Number(order.total_due_nsat).toLocaleString()} NSAT · {order.state.replace("_", " ")} · {new Date(order.created_at).toLocaleDateString()}</span></div>{order.state === "awaiting_payment" || order.state === "partially_paid" ? <button type="button" onClick={() => app.openWallet({ orderId: order.id })}>Continue payment</button> : null}</div>) : <p>No NSAT orders yet. Paid items appear here and in your library.</p>}</section>
          <section className="marketplace__purchase-history"><h2>Purchase history · simulations</h2>{purchases.length ? purchases.map((purchase) => <div className="marketplace__submission" key={purchase.id}><div><strong>{purchase.item.title}</strong><span className="marketplace__history-meta">{purchase.amount_nsat.toLocaleString()} proposed NSAT · {purchase.state} · no chain transfer</span></div>{purchase.dispute_state ? <span>Issue: {purchase.dispute_state}</span> : <details className="marketplace__dispute"><summary>Report an issue</summary><form onSubmit={(event) => submitDispute(event, purchase)}><input name="reason" minLength="5" maxLength="500" required placeholder="Describe the issue" /><button type="submit">Submit simulated dispute</button></form></details>}</div>) : <p>No simulated purchases yet.</p>}</section>
        </> : null}

        {tab === "creator" ? <div className="marketplace__creator">
          <form className="marketplace__form" onSubmit={submit}>
            <h2>Submit an item</h2><p>New items go to moderation. Upload a simple image preview; SVG and active content are not accepted.</p>
            <label>Type<select name="kind" value={submissionKind} onChange={(event) => setSubmissionKind(event.target.value)} required>{CATEGORIES.filter((value) => value !== "all").map((value) => <option value={value} key={value}>{LABELS[value]}</option>)}</select></label>
            <label>Title<input name="title" maxLength="100" required /></label>
            <label>Description<textarea name="description" maxLength="1000" rows="3" /></label>
            <label>Proposed price (NSAT)<input name="price" type="number" min="0" max="1000000000" defaultValue="0" required /><small>1–1,000,000,000 NSAT, charged when a buyer checks out. Leave 0 to publish without a sale price: the item shows as “Not for sale” and cannot be ordered.</small></label>
            <label>Usage rights<input name="rights" maxLength="500" placeholder="Personal in-app use" /></label>
            <label>Preview image<input name="preview" type="file" accept="image/jpeg,image/png,image/webp,image/gif" /></label>
            {submissionKind === "sticker_pack" ? <label>Sticker images<input name="assets" type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple required /><small>Upload 1–30 images, up to 2 MB each. Pack content is reviewed before it appears in chat.</small></label> : null}
            <button type="submit" disabled={acting === "submit"}>{acting === "submit" ? "Submitting…" : "Submit for review"}</button>
          </form>
          <form className="marketplace__form" onSubmit={saveCreatorProfile}>
            <h2>Creator profile</h2><p>Share a public name and short description with your approved collections.</p>
            <label>Display name<input name="creator_name" maxLength="80" defaultValue={dashboard?.profile?.display_name || ""} /></label>
            <label>About<textarea name="creator_bio" maxLength="500" rows="3" defaultValue={dashboard?.profile?.bio || ""} /></label>
            <button type="submit">Save profile</button>
          </form>
          <section className="marketplace__activity"><h2>Your submissions</h2>{dashboard?.items?.length ? dashboard.items.map((item) => <div className="marketplace__submission" key={item.id}><strong>{item.title}</strong><span>{item.kind} · {item.state || "Pending review"}</span></div>) : <p>Your submitted items and simulated creator gift activity will appear here.</p>}<h3>Creator gift activity</h3>{dashboard?.gift_activity?.length ? dashboard.gift_activity.map((gift) => <div className="marketplace__submission" key={gift.id}><strong>{gift.item.title}</strong><span>Simulation · {new Date(gift.created_at).toLocaleString()}</span></div>) : <p>No gift activity yet.</p>}</section>
          <section className="marketplace__activity"><h2>NSAT sales</h2><div className="marketplace__sales-totals"><strong>{dashboard?.sales_totals?.count || 0} sale(s)</strong><span>{Number(dashboard?.sales_totals?.creator_proceeds_nsat || 0).toLocaleString()} NSAT received · {Number(dashboard?.sales_totals?.gross_nsat || 0).toLocaleString()} NSAT gross</span></div>{dashboard?.sales?.length ? dashboard.sales.map((sale) => <div className="marketplace__submission" key={sale.id}><strong>{sale.item}</strong><span>{Number(sale.creator_proceeds_nsat).toLocaleString()} NSAT · {new Date(sale.created_at).toLocaleString()}</span></div>) : <p>No sales yet. Connect an NSAT wallet so buyers can pay you directly.</p>}</section>
          <section className="marketplace__activity"><h2>Notifications</h2>{dashboard?.notifications?.length ? dashboard.notifications.map((notice) => <div className="marketplace__submission" key={notice.id}><strong>{notice.message}</strong><span>{new Date(notice.created_at).toLocaleString()}</span></div>) : <p>No creator notifications yet.</p>}</section>
          <section className="marketplace__activity"><h2>Gift history · simulations</h2>{giftRows.length ? giftRows.map((gift) => <div className="marketplace__submission" key={`${gift.direction}-${gift.id}`}><strong>{gift.direction}: {gift.item.title}</strong><span>{new Date(gift.created_at).toLocaleString()}</span></div>) : <p>No gifts recorded yet.</p>}</section>
        </div> : null}
      </div>
    </section>
  );
}
