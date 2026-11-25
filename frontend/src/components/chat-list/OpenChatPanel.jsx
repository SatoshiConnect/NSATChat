import { useMemo, useState } from "react";
import { MessageSquarePlus, Search, Users } from "lucide-react";
import { useStore } from "../../store/store";
import { listTime } from "../../utils/format";
import { roomTitle } from "../../utils/messages";
import { Avatar, EmptyState, IconButton, PanelHeader, SearchInput } from "../common/ui";
import { useApp } from "../layout/AppContext";

/** OpenChat currently lists joined invite-based group rooms; public discovery is not implemented. */
export default function OpenChatPanel() {
  const app = useApp();
  const me = useStore((state) => state.me);
  const rooms = useStore((state) => state.rooms);
  const contacts = useStore((state) => state.contacts);
  const [query, setQuery] = useState("");
  const contactMap = useMemo(() => new Map(contacts.map((contact) => [Number(contact.contact_user?.id), contact.name])), [contacts]);
  const groups = useMemo(() => Object.values(rooms)
    .filter((room) => room.isGroup && !room.isArchived)
    .filter((room) => roomTitle(room, contactMap, me).toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a, b) => new Date(b.lastMessage?.created_at || b.updatedAt || 0) - new Date(a.lastMessage?.created_at || a.updatedAt || 0)), [rooms, contactMap, me, query]);

  const newGroup = () => {
    app.pushPanel("newGroup");
  };

  return (
    <section className="panel openchat-panel">
      <PanelHeader title="OpenChat" actions={<IconButton icon={MessageSquarePlus} label="Create group" onClick={newGroup} />} />
      <SearchInput value={query} onChange={setQuery} placeholder="Search your groups" />
      <div className="panel__scroll">
        <p className="openchat-note"><strong>Your groups</strong><span>Join by invite link or create a group. Public group discovery is not available yet.</span></p>
        {groups.length ? (
          <div className="list-pad">
            {groups.map((room) => (
              <button type="button" className="row openchat-room" key={room.id} onClick={() => app.openRoom(room.id)}>
                <Avatar src={room.groupPhoto} name={room.groupName} group size={48} />
                <span className="row__body">
                  <span className="row__title">{roomTitle(room, contactMap, me)}</span>
                  <span className="row__subtitle">{room.lastMessage?.content || `${room.participants?.length || 0} members · Private invite group`}</span>
                </span>
                <span className="openchat-room__time">{room.lastMessage?.created_at ? listTime(room.lastMessage.created_at) : ""}</span>
              </button>
            ))}
          </div>
        ) : (
          <EmptyState icon={Search} title={query ? "No groups found" : "No groups yet"} text={query ? "Try another group name." : "Create a group or open an invitation link to join one."}>
            {!query ? <button type="button" className="btn btn--primary" onClick={newGroup}><Users size={16} /> Create group</button> : null}
          </EmptyState>
        )}
      </div>
    </section>
  );
}
