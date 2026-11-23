import { useEffect, useMemo, useRef, useState } from "react";
import { ContactRound, Copy, Mail, MessageCircle, QrCode, ScanLine, Search, Share2, Smartphone, UserPlus, Users } from "lucide-react";
import { authApi, contactsApi } from "../../api/endpoints";
import { errorMessage } from "../../api/client";
import { useDebouncedValue } from "../../hooks";
import { loadContacts, openChatWith } from "../../store/actions";
import { useStore } from "../../store/store";
import { toast } from "../../services/toast";
import { formatPhone, looksLikePhone } from "../../utils/phone";
import { profileName } from "../../utils/messages";
import { normalizePublicIdQuery } from "../../utils/contactLookup";
import { prepareGoogleContacts, requestGoogleContactsAccess, revokeGoogleContacts, syncGooglePeople } from "../../services/googleContacts";
import { Avatar, EmptyState, PanelHeader, SearchInput, Spinner } from "../common/ui";
import { useApp } from "../layout/AppContext";

function AddFriendRow({ user, action, busy, isSaved = false }) {
  const name = profileName(user) || (user.phone_number ? formatPhone(user.phone_number) : `User ${user.id}`);
  return (
    <div className="row add-friend-row">
      <Avatar src={user.profile?.profile_picture} name={name} />
      <span className="row__body">
        <span className="row__title">{name}</span>
        <span className="row__subtitle">{user.public_id ? `@${user.public_id}` : user.phone_number ? formatPhone(user.phone_number) : user.profile?.about}</span>
      </span>
      <button type="button" className="btn btn--text" onClick={action} disabled={busy}>{busy ? <Spinner size={16} /> : isSaved ? <><MessageCircle size={16} /> Chat</> : <><UserPlus size={16} /> Add</>}</button>
    </div>
  );
}

export default function AddFriendsPanel() {
  const app = useApp();
  const me = useStore((state) => state.me);
  const savedContacts = useStore((state) => state.contacts);
  const [tab, setTab] = useState("search");
  const [searchMode, setSearchMode] = useState("id");
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 350).trim();
  const [lookup, setLookup] = useState({ term: "", status: "idle" });
  const [suggestions, setSuggestions] = useState({ status: "idle", users: [] });
  const [busy, setBusy] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [googleSync, setGoogleSync] = useState({ status: "loading", connected: false, matches: [], sync_token: "" });
  const [consentChecked, setConsentChecked] = useState(false);
  const [googleSyncError, setGoogleSyncError] = useState("");
  const [googleClientId, setGoogleClientId] = useState("");
  const [scanning, setScanning] = useState(false);
  const videoRef = useRef(null);
  const [qrData, setQrData] = useState("");
  const savedIds = useMemo(() => new Set(savedContacts.map((item) => String(item.contact_user?.id))), [savedContacts]);

  const normalizedId = normalizePublicIdQuery(debounced);
  const lookupKey = `${searchMode}:${debounced}`;
  const searchable = searchMode === "id" ? Boolean(normalizedId) : looksLikePhone(debounced);
  useEffect(() => {
    if (!searchable) return undefined;
    let cancelled = false;
    const searchTerm = searchMode === "id" ? `@${normalizedId}` : debounced;
    contactsApi.lookup(searchTerm).then((data) => {
      if (!cancelled) setLookup({ term: lookupKey, status: "found", user: data.user, isSelf: data.is_self, saved: data.saved_contact });
    }).catch((error) => {
      if (!cancelled) setLookup({ term: lookupKey, status: "missing", error: errorMessage(error, "No account found.") });
    });
    return () => { cancelled = true; };
  }, [debounced, lookupKey, normalizedId, searchable, searchMode]);

  const result = !searchable ? { status: "idle" } : lookup.term === lookupKey ? lookup : { status: "loading" };
  useEffect(() => {
    let cancelled = false;
    prepareGoogleContacts().catch(() => { /* The button retries initialization with user interaction. */ });
    Promise.allSettled([contactsApi.googleStatus(), authApi.googleConfig()])
      .then(([statusResult, configResult]) => {
        if (cancelled) return;
        if (statusResult.status === "fulfilled") setGoogleSync({ ...statusResult.value, status: "ready" });
        else setGoogleSync({ status: "error", connected: false, matches: [], sync_token: "", error: errorMessage(statusResult.reason, "Contact sync status could not be loaded.") });
        if (configResult.status === "fulfilled") setGoogleClientId(configResult.value.client_id || "");
      })
      .catch(() => !cancelled && setGoogleSync({ status: "error", connected: false, matches: [], sync_token: "", error: "Contact sync status could not be loaded." }));
    return () => { cancelled = true; };
  }, []);
  const shareUrl = useMemo(() => me?.public_id ? `${window.location.origin}/add/${encodeURIComponent(me.public_id)}` : "", [me?.public_id]);
  useEffect(() => {
    let cancelled = false;
    if (shareUrl) {
      import("qrcode").then(({ default: QRCode }) => QRCode.toDataURL(shareUrl, { width: 280, margin: 2, errorCorrectionLevel: "M", color: { dark: "#111827", light: "#ffffff" } }))
        .then((url) => !cancelled && setQrData(url)).catch(() => !cancelled && setQrData(""));
    }
    return () => { cancelled = true; };
  }, [shareUrl]);

  useEffect(() => {
    if (!scanning || tab !== "search" || !videoRef.current) return undefined;
    let cancelled = false;
    let controls;
    import("@zxing/browser").then(({ BrowserQRCodeReader }) => {
      if (cancelled) return null;
      const reader = new BrowserQRCodeReader();
      return reader.decodeFromVideoDevice(undefined, videoRef.current, (result) => {
        if (!result || cancelled) return;
        try {
          const parsed = new URL(result.getText());
          const match = parsed.pathname.match(/^\/add\/([a-z0-9._-]{4,20})$/i);
          if (match) {
            setQuery(`@${decodeURIComponent(match[1])}`);
            setTab("search");
            setScanning(false);
          }
        } catch { /* Ignore QR codes that aren't NSAT friend links. */ }
      });
    }).then((instance) => {
      controls = instance;
      if (cancelled) controls?.stop();
    }).catch((error) => {
      if (!cancelled) { setScanning(false); toast.error(errorMessage(error, "Camera access is unavailable.")); }
    });
    return () => { cancelled = true; controls?.stop(); };
  }, [scanning, tab]);

  async function addUser(user, suggestion = false) {
    setBusy(user.id);
    try {
      let saved;
      if (suggestion || googleSync.matches.some((match) => String(match.id) === String(user.id))) saved = await contactsApi.createSuggestion(profileName(user) || "", user.id);
      else if (user.public_id) saved = await contactsApi.createByPublicId(profileName(user) || "", user.public_id);
      else if (user.phone_number) saved = await contactsApi.create(profileName(user) || formatPhone(user.phone_number), user.phone_number);
      else throw new Error("This account has no public ID or phone number to add.");
      await loadContacts();
      setLookup((current) => current.user?.id === user.id ? { ...current, saved: { id: saved.id, name: saved.name } } : current);
      if (suggestion) setSuggestions((current) => ({ ...current, users: current.users.filter((item) => item.id !== user.id) }));
      toast.success("Friend added to your contacts");
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setBusy(null); }
  }

  async function loadSuggestions() {
    setTab("suggestions");
    if (suggestions.status !== "idle") return;
    setSuggestions({ status: "loading", users: [] });
    try { setSuggestions({ status: "ready", users: await contactsApi.suggestions() }); }
    catch { setSuggestions({ status: "error", users: [] }); }
  }

  async function runGoogleSync() {
    setSyncing(true);
    setGoogleSyncError("");
    try {
      if (!googleClientId) throw new Error("Google Contacts is not configured for this service.");
      const accessToken = await requestGoogleContactsAccess(googleClientId, { silent: googleSync.connected });
      if (!googleSync.connected) await contactsApi.googleSync({ consent_accepted: true });

      const previousSyncToken = googleSync.sync_token || "";
      const syncKey = "satcore_google_contacts_full_sync_id";
      const fullSyncId = previousSyncToken ? "" : (sessionStorage.getItem(syncKey) || crypto.randomUUID());
      if (!previousSyncToken) sessionStorage.setItem(syncKey, fullSyncId);
      const execute = async (cursor, runId) => {
        const nextSyncToken = await syncGooglePeople(accessToken, cursor, async (contacts) => {
          const live = contacts.filter((item) => !item.deleted);
          const deleted = contacts.filter((item) => item.deleted).map((item) => item.resource_name);
          await contactsApi.googleSync({
            contacts: live,
            deleted_resource_names: deleted,
            full_sync: !cursor,
            full_sync_id: runId || undefined,
          });
          setGoogleSync((current) => ({ ...current, status: "syncing" }));
        });
        await contactsApi.googleSync({
          contacts: [],
          full_sync: !cursor,
          full_sync_id: runId || undefined,
          complete: true,
          sync_token: nextSyncToken,
        });
      };
      try {
        await execute(previousSyncToken, fullSyncId);
      } catch (error) {
        if (!(error.status === 410 || error.expiredSyncToken) || !previousSyncToken) throw error;
        const resetId = crypto.randomUUID();
        sessionStorage.setItem(syncKey, resetId);
        await execute("", resetId);
      }
      const state = await contactsApi.googleStatus();
      sessionStorage.removeItem(syncKey);
      setGoogleSync({ ...state, status: "ready" });
      await loadContacts();
      toast.success(`${state.matches.length} SatoshiCore member${state.matches.length === 1 ? "" : "s"} found in Google Contacts`);
    } catch (error) {
      const message = errorMessage(error, error.message || "Google Contacts could not be synced.");
      setGoogleSyncError(message);
      setGoogleSync((current) => ({ ...current, status: "ready" }));
    }
    finally { setSyncing(false); }
  }

  async function disconnectGoogleContacts() {
    if (!window.confirm("Disconnect Google Contacts and delete the synced matches and sync cursor from SatoshiCore?")) return;
    setSyncing(true);
    try {
      let accessToken = "";
      try {
        accessToken = await requestGoogleContactsAccess(googleClientId, { silent: true });
      } catch { /* Server data is still removed; user can revoke Google access in their account settings. */ }
      await contactsApi.googleDisconnect();
      const revoked = await revokeGoogleContacts(accessToken).catch(() => false);
      setGoogleSync({ status: "ready", connected: false, matches: [], sync_token: "" });
      setConsentChecked(false);
      await loadContacts();
      toast.success(revoked ? "Google Contacts disconnected and synced data deleted" : "Synced matches deleted. If needed, revoke Google access from your Google Account permissions.");
    } catch (error) { toast.error(errorMessage(error, "Google Contacts could not be disconnected.")); }
    finally { setSyncing(false); }
  }

  async function openMatchedChat(user) {
    try {
      app.openRoom(await openChatWith(user));
    } catch (error) {
      toast.error(errorMessage(error, "Chat could not be opened."));
    }
  }

  async function shareLink() {
    if (!shareUrl) return;
    try {
      if (navigator.share) await navigator.share({ title: "Add me on SatoshiCore", text: `Find me as @${me.public_id}`, url: shareUrl });
      else { await navigator.clipboard.writeText(shareUrl); toast.success("Friend link copied"); }
    } catch (error) { if (error?.name !== "AbortError") toast.error("Couldn't share this link."); }
  }

  async function copyLink() {
    if (!shareUrl) return;
    try { await navigator.clipboard.writeText(shareUrl); toast.success("Friend link copied"); }
    catch { toast.error("Clipboard access is unavailable. Copy the link manually."); }
  }

  return (
    <section className="panel add-friends">
      <PanelHeader title="Add friends" onBack={app.popPanel} variant="sub" />
      <div className="tabs add-friends__tabs" role="tablist" aria-label="Add friends methods">
        <button className={tab === "search" ? "is-active" : ""} onClick={() => setTab("search")}>Search</button>
        <button className={tab === "qr" ? "is-active" : ""} onClick={() => { setScanning(false); setTab("qr"); }}>QR / Link</button>
        <button className={tab === "contacts" ? "is-active" : ""} onClick={() => { setScanning(false); setTab("contacts"); }}>Contacts</button>
        <button className={tab === "suggestions" ? "is-active" : ""} onClick={() => { setScanning(false); loadSuggestions(); }}>Suggestions</button>
      </div>
      <div className="panel__scroll">
        {tab === "search" ? (
          <>
            <div className="tabs add-friends__search-modes" role="tablist" aria-label="Search by">
              <button type="button" role="tab" aria-selected={searchMode === "id"} className={searchMode === "id" ? "is-active" : ""} onClick={() => { setSearchMode("id"); setQuery(""); }}>User ID</button>
              <button type="button" role="tab" aria-selected={searchMode === "phone"} className={searchMode === "phone" ? "is-active" : ""} onClick={() => { setSearchMode("phone"); setQuery(""); }}>Phone number</button>
            </div>
            <SearchInput value={query} onChange={setQuery} placeholder={searchMode === "id" ? "Enter a public ID" : "Enter phone number with country code"} autoFocus />
            <div className="list-pad add-friends__search-actions">
              <button type="button" className="btn btn--ghost" onClick={() => setScanning(true)}><ScanLine size={17} /> Scan friend QR</button>
            </div>
            {scanning ? <div className="add-friends__scanner"><video ref={videoRef} muted playsInline /><button type="button" className="btn btn--ghost" onClick={() => setScanning(false)}>Stop scanning</button></div> : null}
            {result.status === "loading" ? <div className="list-loading"><Spinner /></div> : null}
            {result.status === "found" ? result.isSelf ? <EmptyState text="That's your own account." /> : result.saved ? <EmptyState title="Already added" text="This person is already in your contacts." /> : (
              <div className="list-pad"><AddFriendRow user={result.user} isSaved={Boolean(result.saved)} busy={busy === result.user.id} action={() => result.saved ? openMatchedChat(result.user) : addUser(result.user)} /></div>
            ) : null}
            {result.status === "missing" ? <EmptyState title="No account found" text={result.error} /> : null}
            {result.status === "idle" ? <EmptyState icon={Search} text={searchMode === "id" ? "Enter the public ID shown on their profile. You can type it with or without @." : "Enter the full phone number, including its country code."} /> : null}
          </>
        ) : null}
        {tab === "qr" ? (
          <div className="add-friends__share">
            {shareUrl ? <>
              {qrData ? <img className="add-friends__qr" src={qrData} alt="Your SatoshiCore add friend QR code" /> : <Spinner />}
              <strong>@{me.public_id}</strong>
              <p>Scan this code or share your link to let people add you.</p>
              <div className="add-friends__buttons">
                <button type="button" className="btn btn--primary" onClick={shareLink}><Share2 size={17} /> Share link</button>
                <button type="button" className="btn btn--ghost" onClick={copyLink}><Copy size={17} /> Copy</button>
                <a className="btn btn--ghost" href={`sms:?body=${encodeURIComponent(`Add me on SatoshiCore: ${shareUrl}`)}`}><Smartphone size={17} /> SMS</a>
                <a className="btn btn--ghost" href={`mailto:?subject=${encodeURIComponent("Add me on SatoshiCore")}&body=${encodeURIComponent(`Find me on SatoshiCore: ${shareUrl}`)}`}><Mail size={17} /> Email</a>
              </div>
            </> : <EmptyState icon={QrCode} title="Set your public ID first" text="A public ID lets people find you and creates your QR code and friend link."><button type="button" className="btn btn--primary" onClick={() => { app.popPanel(); app.setSection("profile"); }}>Set public ID</button></EmptyState>}
          </div>
        ) : null}
        {tab === "contacts" ? (
          <div className="add-friends__contacts">
            <ContactRound size={34} />
            <h3>Sync Google Contacts</h3>
            <p>Use the Google account that holds the contacts you want to check for SatoshiCore members.</p>
            <div className="add-friends__privacy-note">
              <strong>Before you connect</strong>
              <ul>
                <li>Google names and photos are not read. Phone numbers and email addresses are used only to match members.</li>
                <li>Those values are sent securely to SatoshiCore for matching, then discarded. Unmatched details are not saved.</li>
                <li>Only verified members who allow contact discovery can appear. No contacts are sent to Gemini or another AI service.</li>
                <li>We save matched member IDs and an encrypted Google sync cursor so changes can be updated. Disconnect removes those saved sync results.</li>
              </ul>
            </div>
            {googleSync.status === "loading" ? <div className="list-loading"><Spinner /></div> : null}
            {googleSyncError ? <div className="form-error" role="alert">{googleSyncError}</div> : null}
            {googleSync.status === "error" ? <p className="form-error" role="alert">{googleSync.error}</p> : null}
            {googleSync.connected ? (
              <>
                <div className="add-friends__sync-status" role="status">Google Contacts connected · {googleSync.matches.length} member{googleSync.matches.length === 1 ? "" : "s"} found</div>
                <button type="button" className="btn btn--primary" onClick={runGoogleSync} disabled={syncing || googleSync.status === "loading"}>{syncing ? <Spinner size={16} /> : <><Users size={17} /> Sync changes</>}</button>
                {googleSync.matches.length ? <div className="list-pad add-friends__matches">{googleSync.matches.map((user) => (
                  <AddFriendRow key={user.id} user={user} isSaved={savedIds.has(String(user.id))} busy={busy === user.id} action={() => savedIds.has(String(user.id)) ? openMatchedChat(user) : addUser(user, true)} />
                ))}</div> : <EmptyState icon={Users} text="No discoverable SatoshiCore members were found in the synced contacts." />}
                <button type="button" className="btn btn--ghost" onClick={disconnectGoogleContacts} disabled={syncing}>Disconnect and delete sync data</button>
              </>
            ) : (
              <>
                <label className="add-friends__consent">
                  <input type="checkbox" checked={consentChecked} onChange={(event) => setConsentChecked(event.target.checked)} />
                  <span>I agree to use Google Contacts for member discovery as described above.</span>
                </label>
                <button type="button" className="btn btn--primary" onClick={runGoogleSync} disabled={syncing || !consentChecked || googleSync.status === "loading"}>{syncing ? <Spinner size={16} /> : <><Users size={17} /> Continue with Google</>}</button>
                <span className="info-muted">If Google access is unavailable, add friends with their public ID or QR code.</span>
              </>
            )}
          </div>
        ) : null}
        {tab === "suggestions" ? (
          <>
            {suggestions.status === "loading" ? <div className="list-loading"><Spinner /></div> : null}
            {suggestions.status === "ready" && suggestions.users.length ? <div className="list-pad">{suggestions.users.map((user) => <AddFriendRow key={user.id} user={user} isSaved={savedIds.has(String(user.id))} busy={busy === user.id} action={() => savedIds.has(String(user.id)) ? openMatchedChat(user) : addUser(user, true)} />)}</div> : null}
            {suggestions.status === "ready" && !suggestions.users.length ? <EmptyState icon={Users} title="No suggestions yet" text="People who have added you will appear here if you have not added them back." /> : null}
            {suggestions.status === "error" ? <EmptyState text="Suggestions could not be loaded. Try again." /> : null}
          </>
        ) : null}
      </div>
    </section>
  );
}
