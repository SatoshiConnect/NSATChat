import { useEffect, useMemo, useState } from "react";
import { ChevronRight, ContactRound, MessageSquareDashed, Plus, Settings, ShoppingBag, Sparkles, UserPlus, WalletCards } from "lucide-react";
import { marketplaceApi } from "../../api/endpoints";
import { useStore } from "../../store/store";
import { displayUserName } from "../../utils/messages";
import { Avatar, EmptyState, IconButton, PanelHeader } from "../common/ui";
import PresenceAvatar from "../common/PresenceAvatar";
import AdPlacement from "../common/AdPlacement";
import { useApp } from "./AppContext";

const WALLET_UI_ENABLED = import.meta.env.VITE_FEATURE_WALLET_UI !== "false";

export default function HomePanel() {
  const app = useApp();
  const me = useStore((state) => state.me);
  const contacts = useStore((state) => state.contacts);
  const [spotlight, setSpotlight] = useState(null);
  const contactMap = useMemo(() => new Map(contacts.map((contact) => [Number(contact.contact_user?.id), contact.name])), [contacts]);
  const preview = useMemo(() => [...contacts].sort((a, b) => String(a.name).localeCompare(String(b.name))).slice(0, 6), [contacts]);

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
      <PanelHeader title="Home" actions={<IconButton icon={Settings} label="Settings" onClick={() => app.setSection("settings")} />} />
      <div className="panel__scroll">
        <button type="button" className="home-profile" onClick={() => app.setSection("profile")}>
          <Avatar src={me.profile?.profile_picture} name={me.profile?.display_name} size={58} />
          <span className="home-profile__body">
            <strong>{me.profile?.display_name || "Your profile"}</strong>
            <small>{me.public_id ? `@${me.public_id}` : "Set your public ID"}</small>
          </span>
          <ChevronRight size={19} />
        </button>

        <div className="home-shortcuts" aria-label="Quick access">
          <button type="button" onClick={openFriends}><ContactRound size={21} /><span>Friends</span></button>
          <button type="button" onClick={openAddFriends}><UserPlus size={21} /><span>Add friends</span></button>
          <button type="button" onClick={() => app.setSection("openChat")}><MessageSquareDashed size={21} /><span>OpenChat</span></button>
          <button type="button" onClick={() => app.setSection(WALLET_UI_ENABLED ? "wallet" : "marketplace")}>
            {WALLET_UI_ENABLED ? <WalletCards size={21} /> : <ShoppingBag size={21} />}
            <span>{WALLET_UI_ENABLED ? "Wallet" : "Market"}</span>
          </button>
        </div>

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
          <h2>Friends</h2>
          <button type="button" onClick={openFriends}>See all <ChevronRight size={15} /></button>
        </div>
        {preview.length ? (
          <div className="home-friends">
            {preview.map((contact) => {
              const user = contact.contact_user;
              return (
                <button key={contact.id} type="button" className="home-friend" onClick={openFriends}>
                  <PresenceAvatar user={user} src={user?.profile?.profile_picture} name={contact.name || displayUserName(user, contactMap)} size={44} />
                  <span><strong>{contact.name || displayUserName(user, contactMap)}</strong><small>{user?.profile?.about || "SatoshiCore contact"}</small></span>
                  <ChevronRight size={17} />
                </button>
              );
            })}
          </div>
        ) : (
          <EmptyState icon={UserPlus} title="Start with your friends" text="Find people by public ID, QR code, link or selected contacts.">
            <button type="button" className="btn btn--primary" onClick={openAddFriends}><Plus size={16} /> Add friends</button>
          </EmptyState>
        )}
      </div>
    </section>
  );
}
