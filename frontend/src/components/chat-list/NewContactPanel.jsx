import { useEffect, useState } from "react";
import { CheckCircle2, Info, Phone, Trash2, User } from "lucide-react";
import { errorMessage } from "../../api/client";
import { contactsApi } from "../../api/endpoints";
import { useDebouncedValue } from "../../hooks";
import { loadContacts, openChatWith, scheduleRoomsReload } from "../../store/actions";
import { toast } from "../../services/toast";
import { formatPhone, normalizePhone } from "../../utils/phone";
import { profileName } from "../../utils/messages";
import { contactLookupType } from "../../utils/contactLookup";
import { Avatar, PanelHeader, Spinner } from "../common/ui";
import { confirmAction } from "../common/dialogs";
import { useApp } from "../layout/AppContext";


/**
 * Create or edit a saved contact.
 *
 * A saved contact is private to the current user: a name plus a link to an
 * existing SatoshiCore account (found by phone number). Editing the number only
 * re-links this contact to another account — it never changes anybody's
 * account phone number.
 */
export function ContactForm({ contact, initialPhone = "", initialName = "", initialUser = null, sourceRoomId = null, onDone, onCancel, openChatOnCreate = true }) {
  const isEdit = Boolean(contact);
  const addFromChat = !isEdit && Boolean(initialUser?.id && sourceRoomId);
  // null = not typed yet: the name then follows the person's own profile
  // name (set when they signed up), which you can keep or change.
  const [typedName, setTypedName] = useState(contact ? contact.name || "" : initialName || null);
  const [phone, setPhone] = useState(contact?.contact_user?.phone_number || initialPhone || "");
  const debouncedPhone = useDebouncedValue(phone, 450);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const term = debouncedPhone.trim();
  const lookupType = contactLookupType(term);
  const phoneQuery = lookupType === "phone";
  const publicIdQuery = lookupType === "public_id";
  const identifierChanged = term.toLowerCase() !== String(contact?.contact_user?.phone_number || "").trim().toLowerCase();
  const needsLookup = !addFromChat && (phoneQuery || publicIdQuery) && !(isEdit && !identifierChanged);
  const [lookupResult, setLookupResult] = useState({ term: "", state: "idle" });

  useEffect(() => {
    if (!needsLookup) return undefined;
    let cancelled = false;
    contactsApi
      .lookup(term)
      .then((data) => {
        if (cancelled) return;
        if (data.is_self) setLookupResult({ term, state: "error", message: "You can't save your own number." });
        else if (data.saved_contact && data.saved_contact.id !== contact?.id)
          setLookupResult({ term, state: "error", message: `Already saved as "${data.saved_contact.name || formatPhone(data.user.phone_number)}".` });
        else setLookupResult({ term, state: "found", data });
      })
      .catch((err) => !cancelled && setLookupResult({ term, state: "error", message: errorMessage(err, "This phone number isn't on SatoshiCore.") }));
    return () => {
      cancelled = true;
    };
  }, [term, needsLookup, contact]);

  let lookup;
  if (!phoneQuery && !publicIdQuery) lookup = { state: "idle" };
  else if (isEdit && !identifierChanged) lookup = { state: "found", data: { user: contact.contact_user } };
  else lookup = lookupResult.term === term ? lookupResult : { state: "loading" };
  const suggestedName = addFromChat
    ? profileName(initialUser)
    : !isEdit && lookup.state === "found" ? profileName(lookup.data.user) : "";
  const name = typedName ?? suggestedName;
  const setName = setTypedName;

  async function submit(event) {
    event.preventDefault();
    setError("");
    if (!name.trim()) {
      setError("Enter a name for this contact.");
      return;
    }
    if (!addFromChat && lookup.state !== "found") {
      setError("Find an account by phone number or NSAT ID before saving.");
      return;
    }
    setBusy(true);
    try {
      let saved;
      if (isEdit) {
        const fields = { name: name.trim() };
        if (identifierChanged) {
          if (phoneQuery) fields.phone_number = normalizePhone(term);
          else fields.public_id = lookup.data.user.public_id;
        }
        saved = await contactsApi.update(contact.id, fields);
        toast.success("Contact updated");
      } else if (addFromChat) {
        saved = await contactsApi.addFromChat(initialUser.id, sourceRoomId, name.trim());
        toast.success("Friend added to your contacts");
      } else if (lookup.data.user.public_id) {
        saved = await contactsApi.createByPublicId(name.trim(), lookup.data.user.public_id);
        toast.success("Friend added to your contacts");
      } else {
        saved = await contactsApi.create(name.trim(), normalizePhone(term));
        toast.success("Contact saved");
      }
      await loadContacts();
      scheduleRoomsReload();
      if (!isEdit && openChatOnCreate && saved?.contact_user) {
        const roomId = await openChatWith(saved.contact_user);
        onDone?.(saved, roomId);
      } else {
        onDone?.(saved);
      }
    } catch (err) {
      setError(errorMessage(err, "Couldn't save the contact."));
      setBusy(false);
    }
  }

  function remove() {
    confirmAction({
      title: `Delete ${contact.name}?`,
      message: "This removes the contact from your list. Your chat history stays.",
      confirmLabel: "Delete",
      danger: true,
      onConfirm: async () => {
        try {
          await contactsApi.remove(contact.id);
          await loadContacts();
          scheduleRoomsReload();
          toast("Contact deleted");
          onDone?.(null);
        } catch (err) {
          toast.error(errorMessage(err));
        }
      },
    });
  }

  const found = addFromChat ? initialUser : lookup.state === "found" ? lookup.data.user : null;

  return (
    <form className="contact-form" onSubmit={submit} noValidate>
      <div className="contact-form__avatar">
        <Avatar src={found?.profile?.profile_picture} name={name} size={96} />
      </div>
      {error ? <div className="form-error" role="alert">{error}</div> : null}
      <div className="contact-form__field">
        <User size={20} />
        <div className="field">
          <label htmlFor="contact-name">Name</label>
          <input id="contact-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={100} autoFocus />
        </div>
      </div>
      {addFromChat ? (
        <div className="contact-form__field">
          <CheckCircle2 size={20} />
          <div className="field">
            <span className="field__hint">SatoshiCore account</span>
            <strong>{profileName(initialUser) || `User ${initialUser.id}`}</strong>
            {initialUser.public_id ? <span className="field__hint">@{initialUser.public_id}</span> : null}
          </div>
        </div>
      ) : (
        <div className="contact-form__field">
          <Phone size={20} />
          <div className="field">
          <label htmlFor="contact-phone">Phone number or NSAT ID</label>
          <input id="contact-phone" type="text" placeholder="+66… or @your-id" value={phone} onChange={(event) => setPhone(event.target.value)} />
            {lookup.state === "loading" ? <span className="field__hint"><Spinner size={12} /> Checking number…</span> : null}
            {lookup.state === "found" && found ? (
            <span className="lookup-ok">
              <CheckCircle2 size={14} /> SatoshiCore account found{profileName(found) ? ` · ~ ${profileName(found)}` : ""}
              </span>
            ) : null}
            {lookup.state === "error" ? <span className="field__error">{lookup.message}</span> : null}
          </div>
        </div>
      )}
      {isEdit ? (
        <p className="contact-form__note">
          <Info size={16} />
          <span>
            Changing the number links this saved contact to a different SatoshiCore account. It does not change anyone's
            account phone number. The saved name is shown in your chat list, chat header and groups.
          </span>
        </p>
      ) : (
        <p className="contact-form__note">
          <Info size={16} />
          <span>{addFromChat ? "You are chatting with this SatoshiCore account. Save a private contact name to find them easily." : "Find by phone number or NSAT ID. Use Add friends for QR codes, friend links, and contact suggestions. The name you save is private."}</span>
        </p>
      )}
      <div className="contact-form__actions">
        {isEdit ? (
          <button type="button" className="btn btn--text danger-text" onClick={remove}>
            <Trash2 size={16} /> Delete contact
          </button>
        ) : null}
        {onCancel ? <button type="button" className="btn btn--ghost" onClick={onCancel}>Cancel</button> : null}
        <button type="submit" className="btn btn--primary" disabled={busy || lookup.state === "error"}>
          {busy ? <Spinner size={16} /> : "Save"}
        </button>
      </div>
    </form>
  );
}

export default function NewContactPanel({ contact, initialPhone, initialName, initialUser, sourceRoomId }) {
  const app = useApp();
  return (
    <section className="panel">
      <PanelHeader title={contact ? "Edit contact" : "New contact"} onBack={app.popPanel} variant="sub" />
      <div className="panel__scroll">
        <ContactForm
          contact={contact}
          initialPhone={initialPhone}
          initialName={initialName}
          initialUser={initialUser}
          sourceRoomId={sourceRoomId}
          onDone={(saved, roomId) => {
            app.popPanel();
            if (roomId) app.openRoom(roomId);
          }}
        />
      </div>
    </section>
  );
}
