import { Avatar } from "./ui";
import { useStore } from "../../store/store";

/** Avatar that follows live presence events, falling back to the latest API profile snapshot. */
export default function PresenceAvatar({ user, ...props }) {
  const userId = Number(user?.id) || null;
  const presence = useStore((state) => (userId ? state.presence[userId] || null : null));
  const connected = useStore((state) => state.connection === "online");
  const blocked = useStore((state) => (userId ? state.blocked.includes(userId) : false));
  // A stale cached snapshot or presence event must not show blocked users as
  // currently reachable.
  const online = !blocked && connected && Boolean(presence ? presence.is_online : user?.profile?.is_online);
  return <Avatar {...props} online={Boolean(online)} />;
}
