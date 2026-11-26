import { ChevronRight, ShoppingBag, Sparkles } from "lucide-react";

/**
 * Compact first-party promotional placement shared by direct and group chats.
 * Paid campaigns can replace this house promotion when campaign inventory is
 * available; it is intentionally not presented as a paid advertisement.
 */
export default function ConversationAdSlot({ onActivate }) {
  return (
    <aside className="conversation-ad" aria-label="Featured SatoshiCore promotion">
      <div className="conversation-ad__icon" aria-hidden="true"><ShoppingBag size={17} /></div>
      <div className="conversation-ad__copy">
        <span><Sparkles size={12} aria-hidden="true" /> Featured</span>
        <strong>Creator gifts and digital items</strong>
      </div>
      <button type="button" className="conversation-ad__action" onClick={onActivate}>
        Explore <ChevronRight size={15} aria-hidden="true" />
      </button>
    </aside>
  );
}
