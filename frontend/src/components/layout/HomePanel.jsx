import { useMemo } from "react";
import { ChevronRight, ContactRound, MessageSquareDashed, Plus, Settings, ShoppingBag, UserPlus, WalletCards } from "lucide-react";
import { useStore } from "../../store/store";
import { displayUserName } from "../../utils/messages";
import { Avatar, EmptyState, IconButton, PanelHeader } from "../common/ui";
import PresenceAvatar from "../common/PresenceAvatar";
import { useApp } from "./AppContext";

const WALLET_UI_ENABLED = import.meta.env.VITE_FEATURE_WALLET_UI !== "false";

export default function HomePanel() {
  const app = useApp();
  const me = useStore((state) => state.me);
  const contacts = useStore((state) => state.contacts);
  const contactMap = useMemo(() => new Map(contacts.map((contact) => [Number(contact.contact_user?.id), contact.name])), [contacts]);
  const preview = useMemo(() => [...contacts].sort((a, b) => String(a.name).localeCompare(String(b.name))).slice(0, 6), [contacts]);

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
