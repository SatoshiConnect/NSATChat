import { useCallback, useEffect, useRef, useState } from "react";
import { Gift, Library, Search, Sparkles, Store, Upload } from "lucide-react";
import { errorMessage } from "../../api/client";
import { marketplaceApi } from "../../api/endpoints";
import { toast } from "../../services/toast";
import { EmptyState, PanelHeader, Spinner } from "../common/ui";

const CATEGORIES = ["all", "gift", "sticker_pack", "profile_frame", "badge", "theme", "avatar", "pixel_world"];
const LABELS = { all: "Explore", gift: "Gifts", sticker_pack: "Stickers", profile_frame: "Frames", badge: "Badges", theme: "Themes", avatar: "Avatar", pixel_world: "Pixel World" };

export default function MarketplacePanel() {
  const [tab, setTab] = useState("catalog");
  const [kind, setKind] = useState("all");
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState([]);
  const [library, setLibrary] = useState([]);
  const [purchases, setPurchases] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [creators, setCreators] = useState([]);
  const [giftHistory, setGiftHistory] = useState({ received: [], sent: [] });
  const [busy, setBusy] = useState(true);
  const [acting, setActing] = useState(null);
  const purchaseKeys = useRef(new Map());
  const giftRows = [
    ...(giftHistory.received || []).map((gift) => ({ ...gift, direction: "Received" })),
    ...(giftHistory.sent || []).map((gift) => ({ ...gift, direction: "Sent" })),
  ].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  const refresh = useCallback(async () => {
    try {
      const [catalog, inventory, history] = await Promise.all([
        marketplaceApi.catalog({ ...(kind !== "all" ? { kind } : {}), ...(query.trim() ? { q: query.trim() } : {}) }),
        marketplaceApi.inventory(),
        marketplaceApi.purchases(),
      ]);
      setRows(catalog);
      setLibrary(inventory);
      setPurchases(history);
      if (tab === "creator") setDashboard(await marketplaceApi.creatorDashboard());
      if (tab === "creator") setGiftHistory(await marketplaceApi.gifts());
      if (tab === "creators") setCreators(await marketplaceApi.creators());
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }, [kind, query, tab]);

  useEffect(() => {
    let active = true;
    Promise.all([
      marketplaceApi.catalog({ ...(kind !== "all" ? { kind } : {}), ...(query.trim() ? { q: query.trim() } : {}) }),
      marketplaceApi.inventory(),
      marketplaceApi.purchases(),
    ]).then(async ([catalog, inventory, history]) => {
      const creatorData = tab === "creator" ? await marketplaceApi.creatorDashboard() : null;
      const creatorRows = tab === "creators" ? await marketplaceApi.creators() : null;
      const gifts = tab === "creator" ? await marketplaceApi.gifts() : null;
      if (!active) return;
      setRows(catalog);
      setLibrary(inventory);
      setPurchases(history);
      if (creatorData) setDashboard(creatorData);
      if (creatorRows) setCreators(creatorRows);
      if (gifts) setGiftHistory(gifts);
    }).catch((error) => {
      if (active) toast.error(errorMessage(error));
    }).finally(() => {
      if (active) setBusy(false);
    });
    return () => { active = false; };
  }, [kind, query, tab]);

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

  const submit = async (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const data = new FormData(formElement);
    const preview = data.get("preview");
    setActing("submit");
    try {
      await marketplaceApi.submit({ kind: data.get("kind"), title: data.get("title"), description: data.get("description"), proposed_price_nsat: data.get("price"), usage_rights: data.get("rights"), preview: preview?.size ? preview : undefined });
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
          <div className="marketplace__notice">Simulation only · Proposed NSAT prices · No real payment or on-chain transfer</div>
        </div>

        <div className="marketplace__tabs" role="tablist" aria-label="Marketplace sections">
          <button type="button" className={tab === "catalog" ? "is-active" : ""} onClick={() => setTab("catalog")}><Store size={17} /> Explore</button>
          <button type="button" className={tab === "creators" ? "is-active" : ""} onClick={() => setTab("creators")}><Sparkles size={17} /> Creators</button>
          <button type="button" className={tab === "library" ? "is-active" : ""} onClick={() => setTab("library")}><Library size={17} /> My library ({library.length})</button>
          <button type="button" className={tab === "creator" ? "is-active" : ""} onClick={() => setTab("creator")}><Upload size={17} /> Creator studio</button>
        </div>

        {tab === "catalog" ? <>
          <label className="marketplace__search"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search items" aria-label="Search marketplace items" /></label>
          <div className="marketplace__categories">{CATEGORIES.map((value) => <button type="button" key={value} className={kind === value ? "is-active" : ""} onClick={() => setKind(value)}>{LABELS[value]}</button>)}</div>
          {busy ? <div className="marketplace__loading"><Spinner /></div> : rows.length ? <div className="marketplace__grid">{rows.map((item) => (
            <article className="market-item" key={item.id}>
              {item.preview ? <img src={item.preview} alt="" className="market-item__preview" /> : <div className={`market-item__preview market-item__placeholder kind-${item.kind}`}>{item.kind === "gift" ? <Gift /> : <Sparkles />}</div>}
              <div className="market-item__body"><span className="market-item__kind">{LABELS[item.kind] || item.kind}</span><h2>{item.title}</h2><p>{item.description}</p><small>By {item.creator_name}</small><div className="market-item__foot"><strong>{item.price_label}</strong><button type="button" disabled={acting === item.id} onClick={() => simulate(item)}>{acting === item.id ? "Working…" : "Try simulation"}</button></div><details className="market-item__report"><summary>Report item</summary><form onSubmit={(event) => reportItem(event, item)}><select name="reason" defaultValue="copyright"><option value="copyright">Copyright</option><option value="unsafe">Unsafe</option><option value="spam">Spam</option><option value="other">Other</option></select><input name="details" maxLength="1000" placeholder="Details (optional)" /><button type="submit">Send report</button></form></details></div>
            </article>
          ))}</div> : <EmptyState icon={Store} text="No approved items yet" />}
        </> : null}

        {tab === "creators" ? (busy ? <div className="marketplace__loading"><Spinner /></div> : creators.length ? <div className="marketplace__creator-directory">{creators.map((creator) => <article key={creator.user_id}><span className="marketplace__creator-avatar">{creator.display_name.slice(0, 1).toUpperCase()}</span><div><h2>{creator.display_name}</h2><p>{creator.bio}</p><div className="marketplace__creator-items">{creator.approved_items.map((item) => <span key={item.id}>{item.title}</span>)}</div></div></article>)}</div> : <EmptyState icon={Sparkles} text="Creator collections will appear here after items are approved." />) : null}

        {tab === "library" ? <>
          {busy ? <div className="marketplace__loading"><Spinner /></div> : library.length ? <div className="marketplace__grid">{library.map(({ id, item, acquired_at }) => <article className="market-item market-item--library" key={id}><div className="market-item__preview market-item__placeholder"><Library /></div><div className="market-item__body"><span className="market-item__kind">{LABELS[item.kind] || item.kind}</span><h2>{item.title}</h2><p>{item.usage_rights || "Personal in-app use."}</p><small>Added {new Date(acquired_at).toLocaleDateString()}</small><strong className="market-item__owned">Owned · simulated</strong></div></article>)}</div> : <EmptyState icon={Library} text="Your library is empty. Try a simulation from the catalog." />}
          <section className="marketplace__purchase-history"><h2>Purchase history · simulations</h2>{purchases.length ? purchases.map((purchase) => <div className="marketplace__submission" key={purchase.id}><div><strong>{purchase.item.title}</strong><span className="marketplace__history-meta">{purchase.amount_nsat.toLocaleString()} proposed NSAT · {purchase.state} · no chain transfer</span></div>{purchase.dispute_state ? <span>Issue: {purchase.dispute_state}</span> : <details className="marketplace__dispute"><summary>Report an issue</summary><form onSubmit={(event) => submitDispute(event, purchase)}><input name="reason" minLength="5" maxLength="500" required placeholder="Describe the issue" /><button type="submit">Submit simulated dispute</button></form></details>}</div>) : <p>No simulated purchases yet.</p>}</section>
        </> : null}

        {tab === "creator" ? <div className="marketplace__creator">
          <form className="marketplace__form" onSubmit={submit}>
            <h2>Submit an item</h2><p>New items go to moderation. Upload a simple image preview; SVG and active content are not accepted.</p>
            <label>Type<select name="kind" required>{CATEGORIES.filter((value) => value !== "all").map((value) => <option value={value} key={value}>{LABELS[value]}</option>)}</select></label>
            <label>Title<input name="title" maxLength="100" required /></label>
            <label>Description<textarea name="description" maxLength="1000" rows="3" /></label>
            <label>Proposed price (NSAT)<input name="price" type="number" min="0" max="1000000000" defaultValue="0" required /><small>Display only; no token will be charged.</small></label>
            <label>Usage rights<input name="rights" maxLength="500" placeholder="Personal in-app use" /></label>
            <label>Preview image<input name="preview" type="file" accept="image/jpeg,image/png,image/webp,image/gif" /></label>
            <button type="submit" disabled={acting === "submit"}>{acting === "submit" ? "Submitting…" : "Submit for review"}</button>
          </form>
          <form className="marketplace__form" onSubmit={saveCreatorProfile}>
            <h2>Creator profile</h2><p>Share a public name and short description with your approved collections.</p>
            <label>Display name<input name="creator_name" maxLength="80" defaultValue={dashboard?.profile?.display_name || ""} /></label>
            <label>About<textarea name="creator_bio" maxLength="500" rows="3" defaultValue={dashboard?.profile?.bio || ""} /></label>
            <button type="submit">Save profile</button>
          </form>
          <section className="marketplace__activity"><h2>Your submissions</h2>{dashboard?.items?.length ? dashboard.items.map((item) => <div className="marketplace__submission" key={item.id}><strong>{item.title}</strong><span>{item.kind} · {item.state || "Pending review"}</span></div>) : <p>Your submitted items and simulated creator gift activity will appear here.</p>}<h3>Creator gift activity</h3>{dashboard?.gift_activity?.length ? dashboard.gift_activity.map((gift) => <div className="marketplace__submission" key={gift.id}><strong>{gift.item.title}</strong><span>Simulation · {new Date(gift.created_at).toLocaleString()}</span></div>) : <p>No gift activity yet.</p>}</section>
          <section className="marketplace__activity"><h2>Notifications</h2>{dashboard?.notifications?.length ? dashboard.notifications.map((notice) => <div className="marketplace__submission" key={notice.id}><strong>{notice.message}</strong><span>{new Date(notice.created_at).toLocaleString()}</span></div>) : <p>No creator notifications yet.</p>}</section>
          <section className="marketplace__activity"><h2>Gift history · simulations</h2>{giftRows.length ? giftRows.map((gift) => <div className="marketplace__submission" key={`${gift.direction}-${gift.id}`}><strong>{gift.direction}: {gift.item.title}</strong><span>{new Date(gift.created_at).toLocaleString()}</span></div>) : <p>No gifts recorded yet.</p>}</section>
        </div> : null}
      </div>
    </section>
  );
}
