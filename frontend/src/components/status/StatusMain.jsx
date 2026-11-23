import { useCallback, useEffect, useState } from "react";
import { Flag, Image as ImageIcon, MessageCircle, Pencil, Send, ThumbsUp, Trash2, X } from "lucide-react";
import { socialApi } from "../../api/endpoints";
import { mediaUrl, errorMessage } from "../../api/client";
import { useStore } from "../../store/store";
import { toast } from "../../services/toast";
import { Avatar, EmptyState, Spinner } from "../common/ui";
import PresenceAvatar from "../common/PresenceAvatar";
import { detailTime } from "../../utils/format";

function PostCommentItem({ comment, postId, me, onChange }) {
  const [editing, setEditing] = useState(false);
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
  return (
    <article className="social-post">
      <header className="social-post__author">
        <PresenceAvatar user={post.author} src={post.author?.profile?.profile_picture} name={author} size={42} />
        <div><strong>{author}</strong><span>{detailTime(post.created_at)} · {post.visibility === "EVERYONE" ? "Public" : "Contacts"}</span></div>
        {Number(post.author?.id) === Number(me?.id) ? <button type="button" className="social-post__delete" aria-label="Delete post" onClick={async () => { if (!window.confirm("Delete this post?")) return; try { await socialApi.removePost(post.id); await onChange(); } catch (error) { toast.error(errorMessage(error, "Couldn't delete post.")); } }}><Trash2 size={17} /></button> : <button type="button" className="social-post__report-toggle" onClick={() => setReportOpen((open) => !open)} aria-expanded={reportOpen}><Flag size={16} /> Report</button>}
      </header>
      {post.text ? <p className="social-post__text">{post.text}</p> : null}
      {post.image ? <img className="social-post__image" src={mediaUrl(post.image)} alt="Post attachment" loading="lazy" /> : null}
      <div className="social-post__counts"><span>{post.likes_count || 0} likes</span><span>{post.comments_count || comments.length} comments</span></div>
      <div className="social-post__actions">
        <button type="button" className={post.is_liked ? "is-liked" : ""} onClick={async () => { try { await socialApi.toggleLike(post.id); await onChange(); } catch (error) { toast.error(errorMessage(error, "Couldn't update reaction.")); } }}><ThumbsUp size={17} /> Like</button>
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
  const [image, setImage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try { const page = await socialApi.posts({ limit: 20, offset: 0 }); setPosts(page.results || []); setHasMore(Boolean(page.next)); setError(""); }
    catch (cause) { setError(errorMessage(cause, "Couldn't load posts.")); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    let active = true;
    socialApi.posts({ limit: 20, offset: 0 }).then((page) => { if (active) { setPosts(page.results || []); setHasMore(Boolean(page.next)); setError(""); } })
      .catch((cause) => { if (active) setError(errorMessage(cause, "Couldn't load posts.")); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try { const page = await socialApi.posts({ limit: 20, offset: posts.length }); setPosts((current) => [...current, ...(page.results || [])]); setHasMore(Boolean(page.next)); }
    catch (cause) { toast.error(errorMessage(cause, "Couldn't load more posts.")); }
    finally { setLoadingMore(false); }
  };

  const publish = async (event) => {
    event.preventDefault();
    if ((!text.trim() && !image) || busy) return;
    if (image && image.size > 8 * 1024 * 1024) { toast.error("Image must be 8 MB or smaller."); return; }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("text", text.trim());
      form.append("visibility", visibility);
      if (image) form.append("image", image);
      await socialApi.createPost(form);
      setText(""); setImage(null); event.currentTarget.reset();
      await load();
    } catch (cause) { toast.error(errorMessage(cause, "Couldn't publish post.")); }
    finally { setBusy(false); }
  };

  return (
    <section className="social-feed" aria-label="Social posts">
      <header className="social-feed__heading"><div><h2>Posts</h2><p>Persistent updates. Stories stay separate and expire after 24 hours.</p></div></header>
      <form className="social-compose" onSubmit={publish}>
        <div className="social-compose__row"><Avatar src={me?.profile?.profile_picture} name={me?.profile?.display_name} size={40} /><textarea value={text} onChange={(event) => setText(event.target.value)} maxLength={2000} rows={3} placeholder="What's on your mind?" aria-label="Post text" /></div>
        {image ? <div className="social-compose__file">{image.name}<button type="button" onClick={() => setImage(null)} aria-label="Remove image">×</button></div> : null}
        <footer><label className="social-compose__image"><ImageIcon size={18} /> Photo<input type="file" accept="image/jpeg,image/png,image/webp,image/gif" onChange={(event) => setImage(event.target.files?.[0] || null)} /></label><select value={visibility} onChange={(event) => setVisibility(event.target.value)} aria-label="Post audience"><option value="CONTACTS">My contacts</option><option value="EVERYONE">Public</option></select><button className="btn btn--primary" type="submit" disabled={busy || (!text.trim() && !image)}>{busy ? <Spinner size={16} /> : "Post"}</button></footer>
      </form>
      {loading ? <div className="list-loading"><Spinner /></div> : error ? <div className="social-feed__error">{error} <button type="button" onClick={load}>Retry</button></div> : posts.length ? <><div className="social-feed__list">{posts.map((post) => <PostCard key={post.id} post={post} me={me} onChange={load} />)}</div>{hasMore ? <button className="social-feed__more" type="button" disabled={loadingMore} onClick={loadMore}>{loadingMore ? <Spinner size={16} /> : "Load more posts"}</button> : null}</> : <EmptyState text="No posts yet. Share the first update with your contacts." />}
    </section>
  );
}
