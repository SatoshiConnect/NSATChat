import { useState } from "react";
import { useApp } from "./AppContext";
import ChatListPanel from "../chat-list/ChatListPanel";

export default function MobileChatsPanel({ FriendsPanel }) {
  const app = useApp();
  const [view, setView] = useState("chats");
  if (!app.compact) return <ChatListPanel />;

  return (
    <div className="mobile-chats-panel">
      <nav className="mobile-chat-switch" aria-label="Chats and friends" role="tablist">
        <button type="button" role="tab" aria-selected={view === "chats"} className={view === "chats" ? "is-active" : ""} onClick={() => setView("chats")}>Chats</button>
        <button type="button" role="tab" aria-selected={view === "friends"} className={view === "friends" ? "is-active" : ""} onClick={() => setView("friends")}>Friends</button>
      </nav>
      <div className="mobile-chats-panel__body">
        {view === "chats" ? <ChatListPanel /> : FriendsPanel ? <FriendsPanel onBack={() => setView("chats")} /> : <ChatListPanel />}
      </div>
    </div>
  );
}
