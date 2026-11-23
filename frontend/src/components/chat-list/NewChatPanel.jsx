import { useEffect, useMemo, useState } from "react";
import { UserPlus, Users } from "lucide-react";
import { errorMessage } from "../../api/client";
import { contactsApi } from "../../api/endpoints";
import { useDebouncedValue } from "../../hooks";
import { loadContacts, openChatWith } from "../../store/actions";
import { useStore } from "../../store/store";
import { toast } from "../../services/toast";
import { formatPhone, phoneDigits } from "../../utils/phone";
import { contactLookupType } from "../../utils/contactLookup";
import { profileName } from "../../utils/messages";
import { Avatar, EmptyState, PanelHeader, SearchInput, Spinner } from "../common/ui";
import { groupByLetter } from "../../utils/rules";
import { useApp } from "../layout/AppContext";

function ContactRow({ contact, onClick, trailing, subtitle }) {
  const user = contact.contact_user;
  return (
    <button type="button" className="row" onClick={onClick}>
      <Avatar src={user?.profile?.profile_picture} name={contact.name} />
      <span className="row__body">
        <span className="row__title">{contact.name || formatPhone(user?.phone_number)}</span>
        <span className="row__subtitle">{subtitle ?? (user?.profile?.about || formatPhone(user?.phone_number))}</span>
      </span>
      {trailing}
    </button>
  );
}

export default function NewChatPanel() {
  const app = useApp();
  const contacts = useStore((state) => state.contacts);
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 350);
  const [opening, setOpening] = useState(null);

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    const digits = phoneDigits(term);
    const sorted = [...contacts].sort((a, b) => String(a.name).localeCompare(String(b.name)));
    if (!term) return sorted;
    return sorted.filter(
      (contact) =>
        String(contact.name || "").toLowerCase().includes(term) ||
        (digits.length >= 2 && phoneDigits(contact.contact_user?.phone_number).includes(digits)),
    );
  }, [contacts, query]);

  // Explicit ID syntax avoids confusing numeric IDs with phone numbers.
  const term = debounced.trim();
  const shouldLookup = Boolean(contactLookupType(term)) && !filtered.length;
  const [lookupResult, setLookupResult] = useState({ term: "", state: "idle" });
  useEffect(() => {
    if (!shouldLookup) return undefined;
    let cancelled = false;
    contactsApi
      .lookup(term)
      .then((data) => !cancelled && setLookupResult({ term, state: "found", data }))
      .catch((error) => !cancelled && setLookupResult({ term, state: "missing", message: errorMessage(error, "No matching SatoshiCore account was found.") }));
    return () => {
      cancelled = true;
    };
  }, [term, shouldLookup]);
  const lookup = !shouldLookup ? { state: "idle" } : lookupResult.term === term ? lookupResult : { state: "loading" };

  async function open(user) {
    setOpening(user.id);
    try {
      const roomId = await openChatWith(user);
      app.openRoom(roomId);
      app.resetPanels();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setOpening(null);
    }
  }

  async function saveContact(user) {
    setOpening(user.id);
    try {
      const saved = user.public_id
        ? await contactsApi.createByPublicId(profileName(user) || "", user.public_id)
        : await contactsApi.create(profileName(user) || formatPhone(user.phone_number), user.phone_number);
      await loadContacts();
      setLookupResult((current) => current.term === term ? { ...current, data: { ...current.data, saved_contact: { id: saved.id, name: saved.name } } } : current);
      toast.success("Friend added to your contacts");
    } catch (error) { toast.error(errorMessage(error)); }
    finally { setOpening(null); }
  }

  return (
    <section className="panel">
      <PanelHeader title="New chat" onBack={app.popPanel} variant="sub" />
      <SearchInput value={query} onChange={setQuery} placeholder="Search name, public ID, email or phone" autoFocus />
      <div className="panel__scroll">
        {!query ? (
          <div className="list-pad list-pad--top">
            <button type="button" className="row row--action" onClick={() => app.pushPanel("newGroup")}>
              <span className="row__icon-circle"><Users size={22} /></span>
              <span className="row__body"><span className="row__title">New group</span></span>
            </button>
            <button type="button" className="row row--action" onClick={() => app.pushPanel("addFriends")}>
              <span className="row__icon-circle"><UserPlus size={22} /></span>
              <span className="row__body"><span className="row__title">Add friends</span></span>
            </button>
          </div>
        ) : null}

        {lookup.state === "loading" ? <div className="list-loading"><Spinner /></div> : null}
        {lookup.state === "found" && !lookup.data.is_self ? (
          <>
            <div className="section-label">{lookup.data.saved_contact ? "Contact" : "Not in your contacts"}</div>
            <div className="list-pad">
              <button type="button" className="row" onClick={() => open(lookup.data.user)} disabled={opening === lookup.data.user.id}>
                <Avatar src={lookup.data.user.profile?.profile_picture} name={profileName(lookup.data.user)} />
                <span className="row__body">
                  <span className="row__title">{lookup.data.saved_contact?.name || profileName(lookup.data.user) || formatPhone(lookup.data.user.phone_number) || `User ${lookup.data.user.id}`}</span>
                  <span className="row__subtitle">{lookup.data.user.public_id ? `@${lookup.data.user.public_id}` : lookup.data.user.phone_number ? formatPhone(lookup.data.user.phone_number) : "SatoshiCore user"}</span>
                </span>
                {opening === lookup.data.user.id ? <Spinner size={18} /> : null}
              </button>
              {!lookup.data.saved_contact ? (
                <button type="button" className="btn btn--text add-contact-link" onClick={() => saveContact(lookup.data.user)}>
                  <UserPlus size={16} /> Add friend
                </button>
              ) : null}
            </div>
          </>
        ) : null}
        {lookup.state === "found" && lookup.data.is_self ? <EmptyState text="That's your own account." /> : null}
        {lookup.state === "missing" ? <EmptyState title="Not on SatoshiCore" text={lookup.message} /> : null}

        {filtered.length ? (
          groupByLetter(filtered).map(([letter, items]) => (
            <div key={letter}>
              <div className="letter-header">{letter}</div>
              <div className="list-pad">
                {items.map((contact) => (
                  <ContactRow
                    key={contact.id}
                    contact={contact}
                    onClick={() => open(contact.contact_user)}
                    trailing={opening === contact.contact_user?.id ? <Spinner size={18} /> : null}
                  />
                ))}
              </div>
            </div>
          ))
        ) : !query ? (
          <EmptyState title="No contacts yet" text="Find people by public ID or phone, scan a friend QR code, share an invite link, or sync selected contacts.">
            <button type="button" className="btn btn--primary" onClick={() => app.pushPanel("addFriends")}>Find friends</button>
          </EmptyState>
        ) : lookup.state === "idle" ? (
          <EmptyState text={`No contacts match "${query}". Search with ID: username, @username, a full phone number, or email.`} />
        ) : null}
      </div>
    </section>
  );
}
