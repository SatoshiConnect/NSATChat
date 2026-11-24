import { useEffect, useRef, useState } from "react";
import { Camera, Check, ChevronDown, ChevronRight, ChevronUp, ContactRound, Eye, Image as ImageIcon, Info, Mail, Pencil, Phone, Plus, Smile, Sparkles, Trash2, User, X } from "lucide-react";
import { errorMessage } from "../../api/client";
import { authApi, statusApi } from "../../api/endpoints";
import { scheduleRoomsReload } from "../../store/actions";
import { dispatch, useStore } from "../../store/store";
import { toast } from "../../services/toast";
import { formatPhone } from "../../utils/phone";
import { normalizeFiles, openFilePicker } from "../../utils/files";
import { Avatar, Menu, PanelHeader, Spinner } from "../common/ui";
import { confirmAction } from "../common/dialogs";
import { useApp } from "../layout/AppContext";
import EmojiPicker from "../conversation/EmojiPicker";
import CameraCapture from "../media/CameraCapture";
import Lightbox from "../media/Lightbox";

const ABOUT_PRESETS = ["Available", "Busy", "At school", "At the movies", "At work", "Battery about to die", "Can't talk, SatoshiCore only", "In a meeting", "At the gym", "Sleeping", "Urgent calls only"];

function EditableField({ icon: Icon, label, value, maxLength, onSave, hint, presets }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  const [emoji, setEmoji] = useState(false);
  const inputRef = useRef(null);
  const emojiRef = useRef(null);

  async function save(next = draft) {
    const trimmed = next.trim();
    if (!trimmed) {
      toast.error(`${label} can't be empty.`);
      return;
    }
    if (trimmed === value) {
      setEditing(false);
      return;
    }
    setBusy(true);
    const ok = await onSave(trimmed);
    setBusy(false);
    if (ok) setEditing(false);
  }

  return (
    <div className="profile-field">
      <Icon size={20} className="profile-field__icon" />
      <div className="profile-field__body">
        <span className="profile-field__label">{label}</span>
        {editing ? (
          <div className="profile-field__edit">
            <input
              ref={inputRef}
              value={draft}
              maxLength={maxLength}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") save();
                if (event.key === "Escape") setEditing(false);
              }}
              autoFocus
            />
            <span className="profile-field__count">{maxLength - draft.length}</span>
            <span ref={emojiRef}>
              <button type="button" className="icon-btn" aria-label="Emoji" onClick={() => setEmoji((v) => !v)}>
                <Smile size={19} />
              </button>
            </span>
            <button type="button" className="icon-btn" aria-label="Save" onClick={() => save()} disabled={busy}>
              {busy ? <Spinner size={16} /> : <Check size={20} />}
            </button>
            {emoji ? (
              <EmojiPicker
                className="emoji-picker--field"
                ignoreRefs={[emojiRef]}
                onClose={() => setEmoji(false)}
                onPick={(item) => {
                  setDraft((current) => (current + item).slice(0, maxLength));
                  inputRef.current?.focus();
                }}
              />
            ) : null}
          </div>
        ) : (
          <div className="profile-field__value">
            <span>{value || "—"}</span>
            <button type="button" className="icon-btn" aria-label={`Edit ${label}`} onClick={() => { setDraft(value || ""); setEditing(true); }}>
              <Pencil size={18} />
            </button>
          </div>
        )}
        {hint ? <span className="profile-field__hint">{hint}</span> : null}
        {editing && presets ? (
          <div className="profile-presets">
            {presets.map((preset) => (
              <button key={preset} type="button" className="chip" onClick={() => save(preset)}>
                {preset}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ProfileHighlights() {
  const [highlights, setHighlights] = useState([]);
  const [stories, setStories] = useState([]);
  const [title, setTitle] = useState("");
  const [selected, setSelected] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const reload = async () => {
    try {
      const [nextHighlights, nextStories] = await Promise.all([statusApi.highlights(), statusApi.mine()]);
      setHighlights(nextHighlights);
      setStories(nextStories);
      setError("");
    } catch (cause) { setError(errorMessage(cause, "Couldn't load story highlights.")); }
  };
  useEffect(() => { const timer = window.setTimeout(reload, 0); return () => window.clearTimeout(timer); }, []);
  async function perform(action, fallback) {
    setBusy(true);
    try { await action(); await reload(); }
    catch (cause) { toast.error(errorMessage(cause, fallback)); }
    finally { setBusy(false); }
  }
  return (
    <section className="profile-highlights" aria-labelledby="profile-highlights-title">
      <div className="profile-highlights__heading"><div><Sparkles size={19} /><h2 id="profile-highlights-title">Story highlights</h2></div><span>{highlights.length}/20</span></div>
      <form className="profile-highlights__create" onSubmit={(event) => { event.preventDefault(); const value = title.trim(); if (!value || busy) return; perform(async () => { await statusApi.createHighlight(value); setTitle(""); }, "Couldn't create highlight."); }}>
        <input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={40} placeholder="Name a highlight" aria-label="Highlight name" />
        <button className="btn btn--primary" type="submit" disabled={busy || !title.trim() || highlights.length >= 20}><Plus size={16} /> Create</button>
      </form>
      {stories.length ? <div className="profile-highlights__add-story"><label htmlFor="highlight-story-select">Add a current story</label><select id="highlight-story-select" value={selected.highlight || ""} onChange={(event) => setSelected((value) => ({ ...value, highlight: event.target.value }))}><option value="">Choose a highlight</option>{highlights.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select><select aria-label="Choose a story" value={selected.story || ""} onChange={(event) => setSelected((value) => ({ ...value, story: event.target.value }))}><option value="">Choose your story</option>{stories.map((story) => <option key={story.id} value={story.id}>{story.content?.slice(0, 42) || `${story.status_type} · ${new Date(story.created_at).toLocaleString()}`}</option>)}</select><button type="button" className="btn" disabled={busy || !selected.highlight || !selected.story} onClick={() => perform(() => statusApi.addHighlightItem(selected.highlight, Number(selected.story)), "Couldn't add this story.")}><Plus size={16} /> Add</button></div> : null}
      {error ? <p className="profile-highlights__empty">{error} <button type="button" onClick={reload}>Retry</button></p> : null}
      {highlights.length ? <div className="profile-highlights__list">{highlights.map((highlight, index) => <article key={highlight.id} className="profile-highlights__card"><div className="profile-highlights__card-heading"><strong>{highlight.title}</strong><span>{highlight.item_count} stories</span><button type="button" className="icon-btn" aria-label={`Move ${highlight.title} up`} disabled={busy || index === 0} onClick={() => perform(() => statusApi.reorderHighlights(highlights.map((item, i) => i === index ? highlights[index - 1].id : i === index - 1 ? highlight.id : item.id)), "Couldn't reorder highlights.")}><ChevronUp size={16} /></button><button type="button" className="icon-btn" aria-label={`Move ${highlight.title} down`} disabled={busy || index === highlights.length - 1} onClick={() => perform(() => statusApi.reorderHighlights(highlights.map((item, i) => i === index ? highlights[index + 1].id : i === index + 1 ? highlight.id : item.id)), "Couldn't reorder highlights.")}><ChevronDown size={16} /></button><button type="button" className="icon-btn" aria-label={`Rename ${highlight.title}`} disabled={busy} onClick={() => { const next = window.prompt("Rename highlight", highlight.title); if (next?.trim()) perform(() => statusApi.updateHighlight(highlight.id, { title: next.trim() }), "Couldn't rename highlight."); }}><Pencil size={16} /></button><button type="button" className="icon-btn" aria-label={`Delete ${highlight.title}`} disabled={busy} onClick={() => { if (window.confirm(`Delete the “${highlight.title}” highlight? Stories themselves won't be deleted.`)) perform(() => statusApi.removeHighlight(highlight.id), "Couldn't delete highlight."); }}><Trash2 size={16} /></button></div>{highlight.items?.length ? <label className="profile-highlights__cover-select">Cover<select aria-label={`Cover image for ${highlight.title}`} value={highlight.cover_status_id || ""} onChange={(event) => perform(() => statusApi.updateHighlight(highlight.id, { cover_status_id: event.target.value || null }), "Couldn't update highlight cover.")}><option value="">First story</option>{highlight.items.map((story) => <option key={story.id} value={story.id}>{story.content?.slice(0, 36) || `${story.status_type} story`}</option>)}</select></label> : null}<div className="profile-highlights__story-list">{(highlight.items || []).map((story) => <div key={story.id}><span>{story.content?.slice(0, 56) || `${story.status_type} story`}</span><button type="button" aria-label="Remove story from highlight" className="icon-btn" disabled={busy} onClick={() => perform(() => statusApi.removeHighlightItem(highlight.id, story.id), "Couldn't remove story.")}><X size={15} /></button></div>)}</div></article>)}</div> : !error ? <p className="profile-highlights__empty">Save stories here to keep them on your profile after the 24-hour story expires.</p> : null}
    </section>
  );
}

/** Your profile: photo, name, about, phone (WhatsApp Web "Profile"). */
export default function ProfilePanel() {
  const app = useApp();
  const me = useStore((state) => state.me);
  const contacts = useStore((state) => state.contacts);
  const [photoMenu, setPhotoMenu] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [camera, setCamera] = useState(false);
  const [viewing, setViewing] = useState(false);
  const [publicIdDraft, setPublicIdDraft] = useState("");
  const [savingPublicId, setSavingPublicId] = useState(false);
  const [editingEmail, setEditingEmail] = useState(false);
  const [emailDraft, setEmailDraft] = useState(me.email || "");
  const [savingEmail, setSavingEmail] = useState(false);
  const [editingContactPhone, setEditingContactPhone] = useState(false);
  const [contactPhoneDraft, setContactPhoneDraft] = useState(me.profile?.contact_phone || "");
  const [savingContactPhone, setSavingContactPhone] = useState(false);
  const photo = me.profile?.profile_picture;

  async function update(fields, success) {
    try {
      const data = await authApi.updateProfile(fields);
      dispatch({ type: "me", me: data.user || { ...me, profile: { ...me.profile, ...data.profile } } });
      scheduleRoomsReload();
      if (success) toast.success(success);
      return true;
    } catch (error) {
      toast.error(errorMessage(error));
      return false;
    }
  }

  async function uploadPhoto(picked) {
    if (!picked) return;
    const [file] = await normalizeFiles([picked]);
    if (!file.type.startsWith("image/")) {
      toast.error("Choose an image file.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error("Profile photos must be 5 MB or smaller.");
      return;
    }
    setUploading(true);
    await update({ profile_picture: file }, "Profile photo updated");
    setUploading(false);
  }

  async function setPublicId() {
    setSavingPublicId(true);
    try {
      const user = await authApi.setPublicId(publicIdDraft);
      dispatch({ type: "me", me: user });
      setPublicIdDraft("");
      toast.success("Your public ID is set");
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setSavingPublicId(false);
    }
  }

  async function saveEmail(event) {
    event.preventDefault();
    const email = emailDraft.trim();
    if (email === (me.email || "")) {
      setEditingEmail(false);
      return;
    }
    setSavingEmail(true);
    const ok = await update({ email }, email ? "Email updated" : "Email removed");
    setSavingEmail(false);
    if (ok) setEditingEmail(false);
  }

  async function saveContactPhone(event) {
    event.preventDefault();
    const contact_phone = contactPhoneDraft.trim();
    if (contact_phone === (me.profile?.contact_phone || "")) {
      setEditingContactPhone(false);
      return;
    }
    setSavingContactPhone(true);
    const ok = await update({ contact_phone }, contact_phone ? "Contact phone updated" : "Contact phone removed");
    setSavingContactPhone(false);
    if (ok) setEditingContactPhone(false);
  }

  const items = [
    photo ? { label: "View photo", icon: Eye, onClick: () => setViewing(true) } : null,
    { label: "Take photo", icon: Camera, onClick: () => setCamera(true) },
    { label: "Upload photo", icon: ImageIcon, onClick: () => openFilePicker("profile-photo-input") },
    photo
      ? {
          label: "Remove photo",
          icon: Trash2,
          danger: true,
          onClick: () => confirmAction({ title: "Remove profile photo?", confirmLabel: "Remove", danger: true, onConfirm: () => update({ remove_picture: "true" }, "Profile photo removed") }),
        }
      : null,
  ].filter(Boolean);

  return (
    <section className="panel profile-panel">
      <PanelHeader title="Profile" onBack={app.compact ? () => app.setSection("settings") : undefined} />
      <div className="panel__scroll">
        <div className="profile-photo">
          <button type="button" className="profile-photo__btn" onClick={(event) => setPhotoMenu(event.currentTarget)} aria-label="Change profile photo">
            <Avatar src={photo} name={me.profile?.display_name} size={200} />
            <span className="profile-photo__overlay">
              {uploading ? <Spinner size={28} /> : <Camera size={26} />}
              <span>{photo ? "Change profile photo" : "Add profile photo"}</span>
            </span>
          </button>
          <input id="profile-photo-input" type="file" accept="image/*" hidden onChange={(event) => { uploadPhoto(event.target.files?.[0]); event.target.value = ""; }} />
        </div>

        <div className="profile-section-label">Profile information</div>
        <ProfileHighlights />
        <EditableField
          icon={User}
          label="Name"
          value={me.profile?.display_name && me.profile.display_name !== me.phone_number ? me.profile.display_name : ""}
          maxLength={25}
          hint="This is not your username or PIN. This name will be visible to your SatoshiCore contacts."
          onSave={(display_name) => update({ display_name }, "Name updated")}
        />
        <div className="profile-field">
          <User size={20} className="profile-field__icon" />
          <div className="profile-field__body">
            <span className="profile-field__label">User ID</span>
            {me.public_id ? (
              <div className="profile-field__value"><span>@{me.public_id}</span></div>
            ) : (
              <>
                <div className="profile-field__edit">
                  <input
                    aria-label="Choose a public user ID"
                    autoCapitalize="none"
                    autoCorrect="off"
                    maxLength={20}
                    placeholder="e.g. migs.2026"
                    value={publicIdDraft}
                    onChange={(event) => setPublicIdDraft(event.target.value.toLowerCase())}
                    onKeyDown={(event) => { if (event.key === "Enter") setPublicId(); }}
                  />
                  <button type="button" className="icon-btn" aria-label="Save user ID" onClick={setPublicId} disabled={savingPublicId || publicIdDraft.length < 4}>
                    {savingPublicId ? <Spinner size={16} /> : <Check size={20} />}
                  </button>
                </div>
                <span className="profile-field__hint">4–20 lowercase letters, numbers, . - or _. You can set this once; it cannot be changed. Others can search it.</span>
              </>
            )}
          </div>
        </div>
        <EditableField
          icon={Info}
          label="About"
          value={me.profile?.about || ""}
          maxLength={139}
          presets={ABOUT_PRESETS}
          onSave={(about) => update({ about }, "About updated")}
        />
        <div className="profile-section-label profile-section-label--separated">Contact information</div>
        <div className="profile-field">
          <Phone size={20} className="profile-field__icon" />
          <div className="profile-field__body">
            <span className="profile-field__label">Login phone</span>
            <div className="profile-field__value"><span>{me.phone_number ? formatPhone(me.phone_number) : <span className="profile-field__empty">Not linked</span>}</span></div>
            <span className="profile-field__hint">Used to sign in to your account.</span>
          </div>
        </div>
        <div className="profile-field">
          <Phone size={20} className="profile-field__icon" />
          <div className="profile-field__body">
            <span className="profile-field__label">Contact phone · not verified</span>
            {editingContactPhone ? (
              <form className="profile-field__edit" onSubmit={saveContactPhone}>
                <input
                  type="tel"
                  aria-label="Contact phone number"
                  value={contactPhoneDraft}
                  onChange={(event) => setContactPhoneDraft(event.target.value)}
                  onKeyDown={(event) => event.key === "Escape" && setEditingContactPhone(false)}
                  placeholder="+66812345678"
                  maxLength={20}
                  autoComplete="tel"
                  autoFocus
                />
                <button type="submit" className="icon-btn" aria-label="Save contact phone" disabled={savingContactPhone}>
                  {savingContactPhone ? <Spinner size={16} /> : <Check size={20} />}
                </button>
              </form>
            ) : (
              <div className="profile-field__value">
                <span>{me.profile?.contact_phone ? formatPhone(me.profile.contact_phone) : <span className="profile-field__empty">Not added</span>}</span>
                <button type="button" className="icon-btn" aria-label={me.profile?.contact_phone ? "Edit contact phone" : "Add contact phone"} onClick={() => { setContactPhoneDraft(me.profile?.contact_phone || ""); setEditingContactPhone(true); }}>
                  <Pencil size={18} />
                </button>
              </div>
            )}
            <span className="profile-field__hint">Free to update. This number is private and is not used for sign-in or friend search.</span>
          </div>
        </div>
        <div className="profile-field">
          <Mail size={20} className="profile-field__icon" />
          <div className="profile-field__body">
            <span className="profile-field__label">Email</span>
            {editingEmail ? (
              <form className="profile-field__edit" onSubmit={saveEmail}>
                <input
                  type="email"
                  aria-label="Email address"
                  value={emailDraft}
                  onChange={(event) => setEmailDraft(event.target.value)}
                  onKeyDown={(event) => event.key === "Escape" && setEditingEmail(false)}
                  placeholder="you@example.com"
                  maxLength={254}
                  autoComplete="email"
                  autoFocus
                />
                <button type="submit" className="icon-btn" aria-label="Save email" disabled={savingEmail}>
                  {savingEmail ? <Spinner size={16} /> : <Check size={20} />}
                </button>
              </form>
            ) : (
              <div className="profile-field__value">
                <span>{me.email || <span className="profile-field__empty">Not added</span>}</span>
                <button type="button" className="icon-btn" aria-label={me.email ? "Edit email" : "Add email"} onClick={() => { setEmailDraft(me.email || ""); setEditingEmail(true); }}>
                  <Pencil size={18} />
                </button>
              </div>
            )}
            <span className="profile-field__hint">Email is part of your account information and is not your public SatoshiCore ID.</span>
          </div>
        </div>
        <button type="button" className="profile-contact-link" onClick={() => app.setSection("contacts")}>
          <ContactRound size={20} />
          <span><strong>Contacts</strong><small>Manage your saved contacts</small></span>
          <span className="profile-contact-link__count">{contacts.length}</span>
          <ChevronRight size={18} />
        </button>
      </div>
      {photoMenu ? <Menu anchor={photoMenu} items={items} align="left" onClose={() => setPhotoMenu(null)} /> : null}
      {camera ? (
        <div className="camera-modal">
          <CameraCapture onClose={() => setCamera(false)} onCapture={(file) => { setCamera(false); if (file.type.startsWith("image/")) uploadPhoto(file); else toast.error("Take a photo, not a video."); }} />
        </div>
      ) : null}
      {viewing && photo ? (
        <Lightbox
          items={[{ message: { id: "me", sender: me, created_at: new Date().toISOString(), content: "" }, attachment: { id: "p", file: photo, mime_type: "image/jpeg", file_name: "profile.jpg" } }]}
          nameOf={() => "You"}
          onClose={() => setViewing(false)}
        />
      ) : null}
    </section>
  );
}
