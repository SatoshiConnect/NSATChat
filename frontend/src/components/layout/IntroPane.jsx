import { FileText, MessageSquarePlus, Sparkles, UserPlus } from "lucide-react";
import { LogoMark } from "../common/Icons";

/** Right-hand placeholder shown when no conversation is open. */
export default function IntroPane({ onNewChat, onNewContact, onAssistant }) {
  return (
    <section className="intro">
      <div className="intro__card">
        <LogoMark size={72} />
        <h2>SatoshiCore Web</h2>
        <p>Send and receive messages, photos, videos and voice notes. Everything stays in sync across your open tabs.</p>
      </div>
      <div className="intro__actions">
        <button type="button" onClick={onNewChat}>
          <span><MessageSquarePlus size={22} /></span>
          New chat
        </button>
        <button type="button" onClick={onNewContact}>
          <span><UserPlus size={22} /></span>
          Find friends
        </button>
        <button type="button" onClick={onAssistant}>
          <span className="is-accent"><Sparkles size={22} /></span>
          SatoshiCore AI
        </button>
        <button type="button" onClick={onNewChat}>
          <span><FileText size={22} /></span>
          Send document
        </button>
      </div>
    </section>
  );
}
