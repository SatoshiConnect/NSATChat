import { useCallback, useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight, Flag, LockKeyhole, MessageSquarePlus, Search, ShieldCheck, Users, UserPlus, X } from "lucide-react";
import { errorMessage } from "../../api/client";
import { chatApi } from "../../api/endpoints";
import { loadRooms } from "../../store/actions";
import { toast } from "../../services/toast";
import "../../styles/openchat.css";
import { Avatar, EmptyState, IconButton, PanelHeader, SearchInput, Spinner } from "../common/ui";
import { useApp } from "../layout/AppContext";

const CATEGORIES = [
  ["", "All"], ["GENERAL", "General"], ["EDUCATION", "Education"], ["GAMING", "Gaming"],
  ["LOCAL", "Local"], ["TECH", "Technology"], ["BUSINESS", "Business"], ["ENTERTAINMENT", "Entertainment"], ["OTHER", "Other"],
];
const JOIN_LABELS = { OPEN: "Open to join", CODE: "Code required", APPROVAL: "Admin approval" };

export default function OpenChatPanel() {
  const app = useApp();
  const [tab, setTab] = useState("discover");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [communities, setCommunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState(null);
  const [joinFields, setJoinFields] = useState({});
  const [busyId, setBusyId] = useState(null);
  const [requests, setRequests] = useState({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await chatApi.openCommunities({
        ...(tab === "mine" ? { mine: 1, ...(query ? { q: query } : {}) } : { q: query, ...(category ? { category } : {}) }),
        limit: 24,
      });
      setCommunities(result.results || []);
    } catch (cause) {
      setCommunities([]);
      setError(errorMessage(cause, "OpenChat communities could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, [category, query, tab]);

  useEffect(() => {
    const timer = window.setTimeout(() => refresh(), query.trim() ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [query, refresh]);

  useEffect(() => {
    const onChanged = () => refresh();
    window.addEventListener("mhtalk:openchat-updated", onChanged);
    return () => window.removeEventListener("mhtalk:openchat-updated", onChanged);
  }, [refresh]);

  const openCommunity = async (community) => {
    setBusyId(community.id);
    try {
      await loadRooms();
      app.openRoom(community.room_id);
    } catch {
      toast.error("Couldn't open this community chat.");
    } finally {
      setBusyId(null);
    }
  };

  const joinCommunity = async (community) => {
    const fields = joinFields[community.id] || {};
    if (community.join_mode === "CODE" && !fields.join_code?.trim()) {
      toast.error("Enter the community access code.");
      return;
    }
    setBusyId(community.id);
    try {
      const result = await chatApi.joinOpenCommunity(community.id, {
        display_name: fields.display_name || "",
        join_code: fields.join_code || "",
        answer: fields.answer || "",
      });
      if (result.state === "PENDING") {
        toast.success("Join request sent. An admin needs to approve it.");
        setTab("mine");
        window.dispatchEvent(new Event("mhtalk:openchat-updated"));
      } else {
        toast.success("You joined the community.");
        await openCommunity({ ...community, room_id: result.room_id });
      }
    } catch (cause) {
      toast.error(errorMessage(cause, "Couldn't join this community."));
    } finally {
      setBusyId(null);
    }
  };

  const toggleRequests = async (community) => {
    if (requests[community.id]) {
      setRequests((current) => ({ ...current, [community.id]: null }));
      return;
    }
    try {
      const rows = await chatApi.openCommunityRequests(community.id);
      setRequests((current) => ({ ...current, [community.id]: rows }));
    } catch (cause) {
      toast.error(errorMessage(cause, "Couldn't load join requests."));
    }
  };

  const decide = async (community, requestId, decision) => {
    setBusyId(community.id);
    try {
      await chatApi.decideOpenCommunityRequest(community.id, requestId, decision);
      const rows = await chatApi.openCommunityRequests(community.id);
      setRequests((current) => ({ ...current, [community.id]: rows }));
      toast.success(decision === "APPROVED" ? "Member approved." : "Request declined.");
    } catch (cause) {
      toast.error(errorMessage(cause, "Couldn't update the join request."));
    } finally {
      setBusyId(null);
    }
  };

  const report = async (community) => {
    if (!window.confirm(`Report “${community.name}” for review?`)) return;
    try {
      await chatApi.reportOpenCommunity(community.id, "OTHER");
      toast.success("Report sent for review.");
    } catch (cause) {
      toast.error(errorMessage(cause, "Couldn't submit the report."));
    }
  };

  return (
    <section className="panel openchat-panel">
      <PanelHeader title="OpenChat" actions={<IconButton icon={MessageSquarePlus} label="Create community" onClick={() => app.pushPanel("newOpenCommunity")} />} />
      <nav className="openchat-tabs" aria-label="OpenChat sections" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "discover"} className={tab === "discover" ? "is-active" : ""} onClick={() => setTab("discover")}>Discover</button>
        <button type="button" role="tab" aria-selected={tab === "mine"} className={tab === "mine" ? "is-active" : ""} onClick={() => setTab("mine")}>My OpenChats</button>
      </nav>
      <SearchInput value={query} onChange={setQuery} placeholder={tab === "discover" ? "Search communities" : "Search My OpenChats"} />
      <div className="panel__scroll">
        {tab === "discover" ? (
          <div className="openchat-categories" aria-label="Community categories">
            {CATEGORIES.map(([value, label]) => <button key={value || "all"} type="button" className={category === value ? "is-active" : ""} onClick={() => setCategory(value)}>{label}</button>)}
          </div>
        ) : null}
        {loading ? <div className="openchat-loading"><Spinner /> <span>Loading communities…</span></div> : error ? (
          <EmptyState icon={Search} title="Couldn't load OpenChat" text={error}><button type="button" className="btn btn--outline" onClick={refresh}>Retry</button></EmptyState>
        ) : communities.length ? (
          <div className="openchat-cards">
            {communities.map((community) => {
              const expanded = expandedId === community.id;
              const fields = joinFields[community.id] || {};
              return (
                <article className="openchat-card" key={community.id}>
                  <button type="button" className="openchat-card__main" onClick={() => setExpandedId(expanded ? null : community.id)} aria-expanded={expanded}>
                    <Avatar src={community.photo} name={community.name} group size={48} />
                    <span className="openchat-card__copy">
                      <strong>{community.name}</strong>
                      <span className="openchat-card__subtitle">{community.description || community.category_label} · {community.member_count} members</span>
                      <span className="openchat-card__meta">{community.category_label} · {JOIN_LABELS[community.join_mode] || "Community"}</span>
                    </span>
                    {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                  </button>
                  {expanded ? (
                    <div className="openchat-card__details">
                      {community.guidelines ? <div><strong>Guidelines</strong><p>{community.guidelines}</p></div> : <p>Check the community guidelines after joining and be respectful to other members.</p>}
                      {community.tags?.length ? <div className="openchat-card__tags">{community.tags.map((tag) => <span key={tag}>#{tag}</span>)}</div> : null}
                      {community.state === "PENDING" ? <p className="openchat-card__status">Waiting for review before public discovery.</p> : null}
                      {community.has_pending_request ? <p className="openchat-card__status">Your join request is waiting for an admin.</p> : null}
                      {!community.is_member && !community.is_owner && !community.has_pending_request && community.state === "PUBLISHED" ? (
                        <>
                          <div className="openchat-card__identity"><label htmlFor={`community-name-${community.id}`}>Name in this community</label><input id={`community-name-${community.id}`} maxLength={50} value={fields.display_name || ""} onChange={(event) => setJoinFields((current) => ({ ...current, [community.id]: { ...current[community.id], display_name: event.target.value } }))} placeholder="Optional nickname" /></div>
                          {community.join_mode === "CODE" ? <div className="openchat-card__identity"><label htmlFor={`community-code-${community.id}`}>Community code</label><input id={`community-code-${community.id}`} type="password" autoComplete="off" value={fields.join_code || ""} onChange={(event) => setJoinFields((current) => ({ ...current, [community.id]: { ...current[community.id], join_code: event.target.value } }))} /></div> : null}
                          {community.join_mode === "APPROVAL" ? <div className="openchat-card__identity"><label htmlFor={`community-answer-${community.id}`}>Message to the admin (optional)</label><input id={`community-answer-${community.id}`} maxLength={500} value={fields.answer || ""} onChange={(event) => setJoinFields((current) => ({ ...current, [community.id]: { ...current[community.id], answer: event.target.value } }))} /></div> : null}
                        </>
                      ) : null}
                      <div className="openchat-card__actions">
                        {community.is_member ? <button type="button" className="btn btn--primary" disabled={busyId === community.id} onClick={() => openCommunity(community)}><Users size={16} /> Open chat</button> : null}
                        {!community.is_member && !community.is_owner && !community.has_pending_request && community.state === "PUBLISHED" ? <button type="button" className="btn btn--primary" disabled={busyId === community.id} onClick={() => joinCommunity(community)}>{busyId === community.id ? <Spinner size={16} /> : community.join_mode === "APPROVAL" ? <UserPlus size={16} /> : <Check size={16} />} {community.join_mode === "APPROVAL" ? "Request to join" : "Join community"}</button> : null}
                        {community.is_admin ? <button type="button" className="btn btn--outline" onClick={() => toggleRequests(community)}><ShieldCheck size={16} /> Review requests</button> : null}
                        {!community.is_member && !community.is_owner ? <button type="button" className="openchat-report" onClick={() => report(community)} aria-label={`Report ${community.name}`}><Flag size={15} /> Report</button> : null}
                        {community.state === "PENDING" && community.is_owner ? <span className="openchat-card__badge">Pending review</span> : null}
                      </div>
                      {requests[community.id] ? <div className="openchat-requests">{requests[community.id].length ? requests[community.id].map((item) => <div className="openchat-request" key={item.id}><span><strong>{item.display_name}</strong>{item.answer ? <small>{item.answer}</small> : null}</span><button type="button" aria-label="Approve request" disabled={busyId === community.id} onClick={() => decide(community, item.id, "APPROVED")}><Check size={17} /></button><button type="button" aria-label="Decline request" disabled={busyId === community.id} onClick={() => decide(community, item.id, "REJECTED")}><X size={17} /></button></div>) : <p>No pending requests.</p>}</div> : null}
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        ) : (
          <EmptyState icon={tab === "mine" ? LockKeyhole : Search} title={query ? "No communities found" : tab === "mine" ? "No OpenChats yet" : "No communities to show yet"} text={query ? "Try another name or topic." : tab === "mine" ? "Communities you join and requests awaiting approval will appear here." : "Approved communities will appear here. Start one of your own."}>
            {!query ? <button type="button" className="btn btn--primary" onClick={() => app.pushPanel("newOpenCommunity")}><MessageSquarePlus size={16} /> Create community</button> : null}
          </EmptyState>
        )}
      </div>
    </section>
  );
}
