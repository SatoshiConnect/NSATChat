import { useEffect, useMemo, useState } from "react";
import {
  CalendarDays, ChevronRight, ContactRound, MessageSquareDashed, Plus, Search,
  Settings, ShoppingBag, Sparkles, UserPlus, Users, WalletCards,
} from "lucide-react";
import { marketplaceApi } from "../../api/endpoints";
import { useStore } from "../../store/store";
import { displayUserName } from "../../utils/messages";
import { Avatar, EmptyState } from "../common/ui";
import PresenceAvatar from "../common/PresenceAvatar";
import AdPlacement from "../common/AdPlacement";
import { useApp } from "./AppContext";

const WALLET_UI_ENABLED = import.meta.env.VITE_FEATURE_WALLET_UI !== "false";

export default function HomePanel() {
  const app = useApp();
  const me = useStore((state) => state.me);
  const contacts = useStore((state) => state.contacts);
  const rooms = useStore((state) => state.rooms);
  const [spotlight, setSpotlight] = useState(null);
  const [query, setQuery] = useState("");
  const contactMap = useMemo(() => new Map(contacts.map((contact) => [Number(contact.contact_user?.id), contact.name])), [contacts]);
  const groupsCount = useMemo(() => Object.values(rooms).filter((room) => room.isGroup && !room.isArchived).length, [rooms]);
  const friends = useMemo(() => {
    const term = query.trim().toLocaleLowerCase();
    return [...contacts]
      .filter((contact) => {
        if (!term) return true;
        const user = contact.contact_user;
        return [contact.name, displayUserName(user, contactMap), user?.public_id]
          .some((value) => String(value || "").toLocaleLowerCase().includes(term));
      })
      .slice(0, 12);
  }, [contacts, contactMap, query]);

  useEffect(() => {
    let active = true;
    marketplaceApi.catalogPage()
      .then((page) => {
        const featured = page.items.find((item) => item.preview) || page.items[0] || null;
        if (active) setSpotlight(featured);
      })
      .catch(() => {});
    return () => { active = false; };
  }, []);

  const openFriends = () => app.setSection("contacts");
  const openAddFriends = () => {
    app.setSection("chats");
    window.setTimeout(() => app.pushPanel("addFriends"), 0);
  };

  return (
    <section className="panel home-panel">
      <div className="panel__scroll home-panel__scroll">
        <header className="home-toolbar">
          <strong>Home</strong>
          <div>
            <button type="button" aria-label="Add friends" onClick={openAddFriends}><Plus size={21} /></button>
            <button type="button" aria-label="Settings" onClick={() => app.setSection("settings")}><Settings size={20} /></button>
          </div>
        </header>

        <div className="home-identity">
          <button type="button" className="home-identity__text" onClick={() => app.setSection("profile")}>
            <strong>{me?.profile?.display_name || "Your profile"}</strong>
            <span>{me?.profile?.about || (me?.public_id ? `@${me.public_id}` : "Set up your SatoshiCore profile")}</span>
          </button>
          <button type="button" className="home-identity__avatar" aria-label="Open Social and share a status" onClick={() => app.setSection("status")}>
            <Avatar src={me?.profile?.profile_picture} name={me?.profile?.display_name} size={56} />
            <span><Plus size={15} /></span>
          </button>
        </div>

        <label className="home-search">
          <Search size={18} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search friends" aria-label="Search friends" />
          {query ? <button type="button" aria-label="Clear search" onClick={() => setQuery("")}>×</button> : null}
        </label>

        <div className="home-summary" aria-label="Your network">
          <button type="button" onClick={openFriends}>
            <ContactRound size={24} />
            <span><strong>Friends</strong><small>{contacts.length} contacts</small></span>
            <ChevronRight size={17} />
          </button>
          <button type="button" onClick={() => app.setSection("chats")}>
            <Users size={24} />
            <span><strong>Groups</strong><small>{groupsCount} group chats</small></span>
            <ChevronRight size={17} />
          </button>
        </div>

        <section className="home-services" aria-label="Services">
          <div className="home-section-header"><h2>Services</h2></div>
          <div className="home-services__rail">
            <button type="button" onClick={openFriends}><ContactRound /><span>Friends</span></button>
            <button type="button" onClick={openAddFriends}><UserPlus /><span>Add friends</span></button>
            <button type="button" onClick={() => app.setSection("openChat")}><MessageSquareDashed /><span>OpenChat</span></button>
            <button type="button" onClick={() => app.setSection("today")}><CalendarDays /><span>Today</span></button>
            <button type="button" onClick={() => app.setSection("status")}><Users /><span>Social</span></button>
            <button type="button" onClick={() => app.setSection("marketplace")}><ShoppingBag /><span>Market</span></button>
            {WALLET_UI_ENABLED ? <button type="button" onClick={() => app.openWallet()}><WalletCards /><span>Wallet</span></button> : null}
            <button type="button" onClick={() => app.openAssistant()}><Sparkles /><span>AI</span></button>
          </div>
        </section>

        <AdPlacement placement="home-discovery" />
        <button type="button" className="home-poster" onClick={() => app.setSection("marketplace")} aria-label="Explore featured creator items in the marketplace">
          {spotlight?.preview ? <img className="home-poster__image" src={spotlight.preview} alt="" loading="lazy" /> : <span className="home-poster__art" aria-hidden="true"><Sparkles size={40} /></span>}
          <span className="home-poster__shade" aria-hidden="true" />
          <span className="home-poster__copy">
            <small>{spotlight ? "FEATURED CREATOR ITEM" : "SATOSHICORE SPOTLIGHT"}</small>
            <strong>{spotlight?.title || "Discover creator collections"}</strong>
            <span>{spotlight?.description || "Explore gifts, stickers and digital items from SatoshiCore creators."}</span>
            <b>Explore marketplace <ChevronRight size={15} /></b>
          </span>
        </button>

        <div className="home-section-header">
          <h2>{query ? "Search results" : "Friends"}</h2>
          <button type="button" onClick={openFriends}>See all <ChevronRight size={15} /></button>
        </div>
        {friends.length ? (
          <div className="home-friends home-friends--rail">
            {friends.map((contact) => {
              const user = contact.contact_user;
              const name = contact.name || displayUserName(user, contactMap);
              return (
                <button key={contact.id} type="button" className="home-friend" onClick={openFriends}>
                  <PresenceAvatar user={user} src={user?.profile?.profile_picture} name={name} size={44} />
                  <strong>{name}</strong>
                </button>
              );
            })}
          </div>
        ) : (
          <EmptyState icon={UserPlus} title={query ? "No matching friends" : "Start with your friends"} text={query ? "Try another name or public ID." : "Find people by public ID, QR code, link or selected contacts."}>
            {!query ? <button type="button" className="btn btn--primary" onClick={openAddFriends}><Plus size={16} /> Add friends</button> : null}
          </EmptyState>
        )}
      </div>
    </section>
  );
}
