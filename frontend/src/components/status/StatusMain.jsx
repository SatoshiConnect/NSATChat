import { useCallback, useEffect, useState } from "react";
import { Bookmark, Check, Flag, Image as ImageIcon, MessageCircle, Pencil, Send, Trash2, UserPlus, X } from "lucide-react";
import { socialApi } from "../../api/endpoints";
import { mediaUrl, errorMessage } from "../../api/client";
import { useStore } from "../../store/store";
import { toast } from "../../services/toast";
import { Avatar, EmptyState, Spinner } from "../common/ui";
import PresenceAvatar from "../common/PresenceAvatar";
import { detailTime } from "../../utils/format";

const POST_REACTIONS = [{ key: "LIKE", emoji: "👍", label: "Like" }, { key: "LOVE", emoji: "❤️", label: "Love" }, { key: "HAHA", emoji: "😂", label: "Haha" }, { key: "WOW", emoji: "😮", label: "Wow" }, { key: "SAD", emoji: "😢", label: "Sad" }, { key: "CARE", emoji: "🤗", label: "Care" }];

function PostCommentItem({ comment, postId, me, onChange, depth = 0 }) {
  const [editing, setEditing] = useState(false);
  const [replying, setReplying] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [draft, setDraft] = useState(comment.text);
  const [busy, setBusy] = useState(false);
  const authorName = comment.author?.profile?.display_name || "Member";
  const ownComment = Number(comment.author?.id) === Number(me?.id);

  const save = async (event) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      await socialApi.editComment(postId, comment.id, text);
      setEditing(false);
      await onChange();
    } catch (error) {
      toast.error(errorMessage(error, "Couldn't edit comment."));
    } finally { setBusy(false); }
  };

  const remove = async () => {
    if (busy || !window.confirm("Delete this comment?")) return;
    setBusy(true);
    try {
      await socialApi.removeComment(postId, comment.id);
      await onChange();
    } catch (error) {
      toast.error(errorMessage(error, "Couldn't delete comment."));
    } finally { setBusy(false); }
  };

  const submitReply = async (event) => {
    event.preventDefault();
    const text = replyText.trim();
    if (!text || busy || depth > 0) return;
    setBusy(true);
    try { await socialApi.addComment(postId, text, comment.id); setReplyText(""); setReplying(false); await onChange(); }
    catch (error) { toast.error(errorMessage(error, "Couldn't reply to comment.")); }
    finally { setBusy(false); }
  };

  return (
    <div className="social-post__comment">
      <PresenceAvatar user={comment.author} src={comment.author?.profile?.profile_picture} name={authorName} size={28} />
      <div className="social-post__comment-main">
        {editing ? <form className="social-post__comment-edit" onSubmit={save}>
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={1000} rows={2} aria-label="Edit comment" autoFocus />
          <div>
            <button type="button" className="social-post__comment-icon" aria-label="Cancel editing" onClick={() => { setDraft(comment.text); setEditing(false); }} disabled={busy}><X size={16} /></button>
            <button type="submit" className="social-post__comment-save" disabled={busy || !draft.trim()}>{busy ? <Spinner size={14} /> : "Save"}</button>
          </div>
        </form> : <p><strong>{authorName}</strong> {comment.text}</p>}
        {ownComment && !editing ? <div className="social-post__comment-actions">
          <button type="button" className="social-post__comment-icon" aria-label="Edit your comment" onClick={() => setEditing(true)} disabled={busy}><Pencil size={14} /></button>
          <button type="button" className="social-post__comment-icon" aria-label="Delete your comment" onClick={remove} disabled={busy}>{busy ? <Spinner size={14} /> : <Trash2 size={14} />}</button>
        </div> : null}
        {depth === 0 ? <button type="button" className="social-post__reply-toggle" onClick={() => setReplying((value) => !value)}>{replying ? "Cancel reply" : "Reply"}</button> : null}
        {replying && depth === 0 ? <form className="social-post__reply-form" onSubmit={submitReply}><input value={replyText} onChange={(event) => setReplyText(event.target.value)} maxLength={1000} placeholder="Write a reply…" aria-label="Write a reply" /><button type="submit" disabled={!replyText.trim() || busy}>{busy ? <Spinner size={14} /> : <Send size={15} />}</button></form> : null}
        {depth === 0 ? (comment.replies || []).map((reply) => <PostCommentItem key={reply.id} comment={reply} postId={postId} me={me} onChange={onChange} depth={1} />) : null}
      </div>
    </div>
  );
}

function PostCard({ post, me, onChange }) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportReason, setReportReason] = useState("SPAM");
  const [reportDetails, setReportDetails] = useState("");
  const [reportBusy, setReportBusy] = useState(false);
  const [saved, setSaved] = useState(Boolean(post.is_saved));
  const [saving, setSaving] = useState(false);
  const author = post.author?.profile?.display_name || post.author?.public_id || "SatoshiCore member";
  const comments = (post.comments || []).filter((item) => item.text);
  const submitComment = async (event) => {
    event.preventDefault();
    const text = comment.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      await socialApi.addComment(post.id, text);
      setComment("");
      await onChange();
    } catch (error) { toast.error(errorMessage(error, "Couldn't post comment.")); }
    finally { setBusy(false); }
  };
  const submitReport = async (event) => {
    event.preventDefault();
    if (reportBusy) return;
    setReportBusy(true);
    try {
      const result = await socialApi.reportPost(post.id, { reason: reportReason, details: reportDetails.trim() });
      toast.success(result.detail || "Thanks. Your report was sent for review.");
      setReportOpen(false);
    } catch (error) { toast.error(errorMessage(error, "Couldn't send report.")); }
    finally { setReportBusy(false); }
  };
  const toggleSave = async () => {
    if (saving) return;
    setSaving(true);
    try { if (saved) await socialApi.unsavePost(post.id); else await socialApi.savePost(post.id); setSaved((value) => !value); }
    catch (error) { toast.error(errorMessage(error, "Couldn't save this post.")); }
    finally { setSaving(false); }
  };
  return (
    <article className="social-post">
      <header className="social-post__author">
        <PresenceAvatar user={post.author} src={post.author?.profile?.profile_picture} name={author} size={42} />
        <div><strong>{author}</strong><span>{detailTime(post.created_at)} · {post.visibility === "EVERYONE" ? "Public" : post.visibility === "FOLLOWERS" ? "Followers" : "Contacts"}</span></div>
        {Number(post.author?.id) === Number(me?.id) ? <><button type="button" className="social-post__delete" aria-label="Edit post" onClick={async () => { const text = window.prompt("Edit your post", post.text); if (text === null) return; try { await socialApi.updatePost(post.id, { text }); await onChange(); } catch (error) { toast.error(errorMessage(error, "Couldn't edit post.")); } }}><Pencil size={16} /></button><button type="button" className="social-post__delete" aria-label="Delete post" onClick={async () => { if (!window.confirm("Delete this post?")) return; try { await socialApi.removePost(post.id); await onChange(); } catch (error) { toast.error(errorMessage(error, "Couldn't delete post.")); } }}><Trash2 size={17} /></button></> : <button type="button" className="social-post__report-toggle" onClick={() => setReportOpen((open) => !open)} aria-expanded={reportOpen}><Flag size={16} /> Report</button>}
      </header>
      {post.text ? <p className="social-post__text">{post.text}</p> : null}
      {post.attachments?.length ? <div className={`social-post__media social-post__media--${Math.min(post.attachments.length, 4)}`}>{post.attachments.map((attachment) => attachment.kind === "VIDEO" ? <video key={attachment.id} className="social-post__image" src={mediaUrl(attachment.url)} controls playsInline preload="metadata" /> : <img key={attachment.id} className="social-post__image" src={mediaUrl(attachment.url)} alt="Post attachment" loading="lazy" />)}</div> : post.image ? <img className="social-post__image" src={mediaUrl(post.image)} alt="Post attachment" loading="lazy" /> : null}
      <div className="social-post__counts"><span>{post.likes_count || 0} reactions</span><span>{post.comments_count || comments.length} comments</span></div>
      <div className="social-post__actions">
        <div className="social-post__reaction-picker" aria-label="React to post">{POST_REACTIONS.map((reaction) => <button key={reaction.key} type="button" className={post.my_reaction === reaction.key ? "is-liked" : ""} aria-label={reaction.label} aria-pressed={post.my_reaction === reaction.key} title={reaction.label} onClick={async () => { try { await socialApi.toggleLike(post.id, reaction.key); await onChange(); } catch (error) { toast.error(errorMessage(error, "Couldn't update reaction.")); } }}>{reaction.emoji}{post.reactions?.[reaction.key] ? <small>{post.reactions[reaction.key]}</small> : null}</button>)}</div>
        <button type="button" className={saved ? "is-liked" : ""} onClick={toggleSave} disabled={saving}><Bookmark size={17} /> {saved ? "Saved" : "Save"}</button>
        <span><MessageCircle size={17} /> Comment</span>
      </div>
      {reportOpen ? <form className="social-post__report-form" onSubmit={submitReport}>
        <label>Reason<select value={reportReason} onChange={(event) => setReportReason(event.target.value)}><option value="SPAM">Spam or misleading</option><option value="HARASSMENT">Harassment</option><option value="HATE">Hate or abusive content</option><option value="SEXUAL">Sexual content</option><option value="VIOLENCE">Violence or dangerous content</option><option value="SCAM">Scam or fraud</option><option value="OTHER">Other</option></select></label>
        <textarea value={reportDetails} onChange={(event) => setReportDetails(event.target.value)} maxLength={1000} rows={2} placeholder="Add details (optional)" />
        <div><button type="button" className="btn btn--ghost" onClick={() => setReportOpen(false)} disabled={reportBusy}>Cancel</button><button type="submit" className="btn btn--primary" disabled={reportBusy}>{reportBusy ? <Spinner size={16} /> : "Send report"}</button></div>
      </form> : null}
      {comments.slice(-3).map((item) => <PostCommentItem key={item.id} comment={item} postId={post.id} me={me} onChange={onChange} />)}
      <form className="social-post__comment-form" onSubmit={submitComment}><input value={comment} onChange={(event) => setComment(event.target.value)} maxLength={1000} placeholder="Write a comment…" aria-label="Write a comment" /><button type="submit" disabled={!comment.trim() || busy} aria-label="Post comment">{busy ? <Spinner size={16} /> : <Send size={17} />}</button></form>
    </article>
  );
}

export default function StatusMain() {
  const me = useStore((state) => state.me);
  const [posts, setPosts] = useState([]);
  const [text, setText] = useState("");
  const [visibility, setVisibility] = useState("CONTACTS");
  const [uploads, setUploads] = useState([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [scope, setScope] = useState("all");
  const [followRequests, setFollowRequests] = useState([]);
  const [requestsBusy, setRequestsBusy] = useState(false);
  const load = useCallback(async () => {
    try { const page = await socialApi.posts({ limit: 20, offset: 0, ...(scope !== "all" ? { scope } : {}) }); setPosts(page.results || []); setHasMore(Boolean(page.next)); setError(""); }
    catch (cause) { setError(errorMessage(cause, "Couldn't load posts.")); }
    finally { setLoading(false); }
  }, [scope]);
  useEffect(() => {
    let active = true;
    socialApi.posts({ limit: 20, offset: 0, ...(scope !== "all" ? { scope } : {}) }).then((page) => { if (active) { setPosts(page.results || []); setHasMore(Boolean(page.next)); setError(""); } })
      .catch((cause) => { if (active) setError(errorMessage(cause, "Couldn't load posts.")); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [scope]);
  useEffect(() => {
    let active = true;
    socialApi.followRequests().then((items) => { if (active) setFollowRequests(items); }).catch(() => {});
    return () => { active = false; };
  }, []);
  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try { const page = await socialApi.posts({ limit: 20, offset: posts.length, ...(scope !== "all" ? { scope } : {}) }); setPosts((current) => [...current, ...(page.results || [])]); setHasMore(Boolean(page.next)); }
    catch (cause) { toast.error(errorMessage(cause, "Couldn't load more posts.")); }
    finally { setLoadingMore(false); }
  };

  const publish = async (event) => {
    event.preventDefault();
    if ((!text.trim() && !uploads.length) || busy) return;
    if (uploads.length > 9) { toast.error("Choose up to 8 images or one video."); return; }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("text", text.trim());
      form.append("visibility", visibility);
      uploads.forEach((file) => form.append("uploads", file));
      await socialApi.createPost(form);
      setText(""); setUploads([]); event.currentTarget.reset();
      await load();
    } catch (cause) { toast.error(errorMessage(cause, "Couldn't publish post.")); }
    finally { setBusy(false); }
  };

  const answerFollow = async (request, action) => {
    if (requestsBusy) return;
    setRequestsBusy(true);
    try {
      await socialApi.answerFollowRequest(request.id, action);
      setFollowRequests((current) => current.filter((item) => item.id !== request.id));
      toast.success(action === "accept" ? "Follow request accepted." : "Request declined.");
    } catch (cause) { toast.error(errorMessage(cause, "Couldn't update follow request.")); }
    finally { setRequestsBusy(false); }
  };

  return (
    <section className="social-feed" aria-label="Social posts">
      <header className="social-feed__heading"><div><h2>Posts</h2><p>Persistent updates. Stories stay separate and expire after 24 hours.</p></div></header>
      <nav className="social-feed__tabs" aria-label="Post feed"><button type="button" className={scope === "all" ? "is-active" : ""} onClick={() => { setLoading(true); setScope("all"); }}>All posts</button><button type="button" className={scope === "following" ? "is-active" : ""} onClick={() => { setLoading(true); setScope("following"); }}>Following</button><button type="button" className={scope === "saved" ? "is-active" : ""} onClick={() => { setLoading(true); setScope("saved"); }}>Saved</button></nav>
      {followRequests.length ? <section className="social-follow-requests" aria-label="Follow requests"><h3><UserPlus size={17} /> Follow requests <span>{followRequests.length}</span></h3>{followRequests.map((request) => <div key={request.id} className="social-follow-requests__row"><PresenceAvatar user={request.user} src={request.user?.profile?.profile_picture} name={request.user?.profile?.display_name || request.user?.public_id || "Member"} size={36} /><span>{request.user?.profile?.display_name || request.user?.public_id || "Member"}</span><button type="button" aria-label="Accept follow request" disabled={requestsBusy} onClick={() => answerFollow(request, "accept")}><Check size={17} /></button><button type="button" aria-label="Decline follow request" disabled={requestsBusy} onClick={() => answerFollow(request, "decline")}><X size={17} /></button></div>)}</section> : null}
      <form className="social-compose" onSubmit={publish}>
        <div className="social-compose__row"><Avatar src={me?.profile?.profile_picture} name={me?.profile?.display_name} size={40} /><textarea value={text} onChange={(event) => setText(event.target.value)} maxLength={2000} rows={3} placeholder="What's on your mind?" aria-label="Post text" /></div>
        {uploads.length ? <div className="social-compose__files">{uploads.map((file, index) => <div className="social-compose__file" key={`${file.name}-${file.lastModified}-${index}`}>{file.name}<button type="button" onClick={() => setUploads((current) => current.filter((_, itemIndex) => itemIndex !== index))} aria-label={`Remove ${file.name}`}>×</button></div>)}</div> : null}
        <footer><label className="social-compose__image"><ImageIcon size={18} /> Photo or video<input type="file" accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime,video/webm" multiple onChange={(event) => { setUploads(Array.from(event.target.files || [])); }} /></label><select value={visibility} onChange={(event) => setVisibility(event.target.value)} aria-label="Post audience"><option value="CONTACTS">My contacts</option><option value="FOLLOWERS">Followers</option><option value="EVERYONE">Public</option></select><button className="btn btn--primary" type="submit" disabled={busy || (!text.trim() && !uploads.length)}>{busy ? <Spinner size={16} /> : "Post"}</button></footer>
      </form>
      {loading ? <div className="list-loading"><Spinner /></div> : error ? <div className="social-feed__error">{error} <button type="button" onClick={load}>Retry</button></div> : posts.length ? <><div className="social-feed__list">{posts.map((post) => <PostCard key={post.id} post={post} me={me} onChange={load} />)}</div>{hasMore ? <button className="social-feed__more" type="button" disabled={loadingMore} onClick={loadMore}>{loadingMore ? <Spinner size={16} /> : "Load more posts"}</button> : null}</> : <EmptyState text={scope === "saved" ? "You have no saved posts yet." : scope === "following" ? "No posts from followed accounts yet." : "No posts yet. Share the first update with your contacts."} />}
    </section>
  );
}
