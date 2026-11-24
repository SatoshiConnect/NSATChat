import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bookmark, Check, Flag, Image as ImageIcon, MessageCircle, Pencil, Send, Share2, Trash2, UserPlus, X } from "lucide-react";
import { socialApi } from "../../api/endpoints";
import { mediaUrl, errorMessage } from "../../api/client";
import { useStore } from "../../store/store";
import { toast } from "../../services/toast";
import { Avatar, EmptyState, Spinner } from "../common/ui";
import PresenceAvatar from "../common/PresenceAvatar";
import { detailTime } from "../../utils/format";
import { contactsByUser, roomTitle } from "../../utils/messages";
import { optimizeStatusImage } from "../../utils/statusImageOptimization";
import LazyVideo from "../media/LazyVideo";

const SOCIAL_IMAGE_LIMIT = 8 * 1024 * 1024;
const SOCIAL_VIDEO_LIMIT = 50 * 1024 * 1024;
const SOCIAL_IMAGE_TOTAL_LIMIT = 32 * 1024 * 1024;
const SOCIAL_IMAGE_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp", "gif"]);
const SOCIAL_VIDEO_EXTENSIONS = new Set(["mp4", "m4v", "mov", "webm"]);

function validatePostFiles(files) {
  if (!files.length) return "";
  const videos = files.filter((file) => SOCIAL_VIDEO_EXTENSIONS.has(file.name.split(".").pop().toLowerCase()));
  const images = files.filter((file) => SOCIAL_IMAGE_EXTENSIONS.has(file.name.split(".").pop().toLowerCase()));
  if (videos.length + images.length !== files.length) return "Choose JPEG, PNG, WebP, GIF, MP4, MOV, M4V, or WebM files.";
  if (videos.length && (videos.length !== 1 || images.length)) return "Choose either one video or up to 8 images.";
  if (images.length > 8) return "Choose up to 8 images.";
  if (images.some((file) => file.size > SOCIAL_IMAGE_LIMIT)) return "Each image must be 8 MB or smaller.";
  if (images.reduce((sum, file) => sum + file.size, 0) > SOCIAL_IMAGE_TOTAL_LIMIT) return "Selected images must total 32 MB or less.";
  if (videos.some((file) => file.size > SOCIAL_VIDEO_LIMIT)) return "Video must be 50 MB or smaller.";
  return "";
}

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

function PostCard({ post, me, onChange, onHashtag }) {
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
      {post.hashtags?.length ? <div className="social-post__hashtags">{post.hashtags.map((tag) => <button type="button" key={tag} onClick={() => onHashtag(tag)}>#{tag}</button>)}</div> : null}
      {post.attachments?.length ? <div className={`social-post__media social-post__media--${Math.min(post.attachments.length, 4)}`}>{post.attachments.map((attachment) => attachment.kind === "VIDEO" ? <LazyVideo key={attachment.id} className="social-post__image social-post__image--video" src={mediaUrl(attachment.url)} controls playsInline /> : <img key={attachment.id} className="social-post__image" src={mediaUrl(attachment.url)} alt="Post attachment" loading="lazy" decoding="async" />)}</div> : post.image ? <img className="social-post__image" src={mediaUrl(post.image)} alt="Post attachment" loading="lazy" decoding="async" /> : null}
      <div className="social-post__counts"><span>{post.likes_count || 0} reactions</span><span>{post.comments_count || comments.length} comments</span></div>
      <div className="social-post__actions">
        <div className="social-post__reaction-picker" aria-label="React to post">{POST_REACTIONS.map((reaction) => <button key={reaction.key} type="button" className={post.my_reaction === reaction.key ? "is-liked" : ""} aria-label={reaction.label} aria-pressed={post.my_reaction === reaction.key} title={reaction.label} onClick={async () => { try { await socialApi.toggleLike(post.id, reaction.key); await onChange(); } catch (error) { toast.error(errorMessage(error, "Couldn't update reaction.")); } }}>{reaction.emoji}{post.reactions?.[reaction.key] ? <small>{post.reactions[reaction.key]}</small> : null}</button>)}</div>
        <button type="button" className={saved ? "is-liked" : ""} onClick={toggleSave} disabled={saving}><Bookmark size={17} /> {saved ? "Saved" : "Save"}</button>
        <button type="button" onClick={() => onChange({ sharePostId: post.id })}><Share2 size={17} /> Share</button>
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
  const rooms = useStore((state) => state.rooms);
  const contacts = useStore((state) => state.contacts);
  const contactMap = useMemo(() => contactsByUser(contacts), [contacts]);
  const [posts, setPosts] = useState([]);
  const [text, setText] = useState("");
  const [visibility, setVisibility] = useState("CONTACTS");
  const [uploads, setUploads] = useState([]);
  const [optimizePhotos, setOptimizePhotos] = useState(true);
  const [preparingPhotos, setPreparingPhotos] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [scope, setScope] = useState("all");
  const [hashtagFilter, setHashtagFilter] = useState("");
  const [followRequests, setFollowRequests] = useState([]);
  const [requestsBusy, setRequestsBusy] = useState(false);
  const [sharingPostId, setSharingPostId] = useState(null);
  const [shareBusy, setShareBusy] = useState(false);
  const feedListRef = useRef(null);
  const scrollToNewestRef = useRef(false);
  const load = useCallback(async (options = {}) => {
    if (options.sharePostId) { setSharingPostId(options.sharePostId); return; }
    try { const page = await socialApi.posts({ limit: 20, offset: 0, ...(scope !== "all" ? { scope } : {}), ...(hashtagFilter ? { hashtag: hashtagFilter } : {}) }); setPosts(page.results || []); setHasMore(Boolean(page.next)); setError(""); }
    catch (cause) { setError(errorMessage(cause, "Couldn't load posts.")); }
    finally { setLoading(false); }
  }, [scope, hashtagFilter]);
  useEffect(() => {
    let active = true;
    socialApi.posts({ limit: 20, offset: 0, ...(scope !== "all" ? { scope } : {}), ...(hashtagFilter ? { hashtag: hashtagFilter } : {}) }).then((page) => { if (active) { setPosts(page.results || []); setHasMore(Boolean(page.next)); setError(""); } })
      .catch((cause) => { if (active) setError(errorMessage(cause, "Couldn't load posts.")); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [scope, hashtagFilter]);
  useEffect(() => {
    if (!scrollToNewestRef.current || !posts.length) return;
    scrollToNewestRef.current = false;
    const list = feedListRef.current;
    // On phones, StatusPanel owns the scroll via .panel__scroll; the
    // .status-mobile-posts wrapper is only a layout container. On desktop,
    // MainLayout gives the Status main pane its own scroll area.
    const scroller = list?.closest(".panel__scroll") || list?.closest(".main--status > .social-feed") || list?.closest(".main--status");
    if (!list || !scroller) return;
    const top = list.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
    scroller.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
  }, [posts]);
  useEffect(() => {
    let active = true;
    socialApi.followRequests().then((items) => { if (active) setFollowRequests(items); }).catch(() => {});
    return () => { active = false; };
  }, []);
  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try { const page = await socialApi.posts({ limit: 20, offset: posts.length, ...(scope !== "all" ? { scope } : {}), ...(hashtagFilter ? { hashtag: hashtagFilter } : {}) }); setPosts((current) => [...current, ...(page.results || [])]); setHasMore(Boolean(page.next)); }
    catch (cause) { toast.error(errorMessage(cause, "Couldn't load more posts.")); }
    finally { setLoadingMore(false); }
  };

  const publish = async (event) => {
    event.preventDefault();
    if ((!text.trim() && !uploads.length) || busy) return;
    const fileError = validatePostFiles(uploads);
    if (fileError) { toast.error(fileError); return; }
    setBusy(true);
    setPreparingPhotos(false);
    setUploadProgress(0);
    try {
      const form = new FormData();
      form.append("text", text.trim());
      form.append("visibility", visibility);
      const preparedUploads = [];
      if (optimizePhotos && uploads.some((file) => SOCIAL_IMAGE_EXTENSIONS.has(file.name.split(".").pop().toLowerCase()))) {
        setPreparingPhotos(true);
      }
      for (const file of uploads) {
        const isImage = SOCIAL_IMAGE_EXTENSIONS.has(file.name.split(".").pop().toLowerCase());
        preparedUploads.push(optimizePhotos && isImage ? await optimizeStatusImage(file) : file);
      }
      setPreparingPhotos(false);
      const imageBytes = preparedUploads.filter((file) => SOCIAL_IMAGE_EXTENSIONS.has(file.name.split(".").pop().toLowerCase())).reduce((sum, file) => sum + file.size, 0);
      if (imageBytes > SOCIAL_IMAGE_TOTAL_LIMIT) throw new Error("Optimized images still exceed the 32 MB combined limit. Remove an image or keep fewer photos.");
      preparedUploads.forEach((file) => form.append("uploads", file));
      const created = await socialApi.createPost(form, (event) => {
        if (event.total) setUploadProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      });
      // The file input is cleared on selection. Do not use event.currentTarget
      // after the async request: React may have cleared it by this point.
      setText(""); setUploads([]);
      if (scope === "all" && !hashtagFilter) {
        scrollToNewestRef.current = true;
        setPosts((current) => [created, ...current.filter((post) => post.id !== created.id)]);
      }
      toast.success("Post published.");
      void load();
    } catch (cause) { toast.error(errorMessage(cause, "Couldn't publish post.")); }
    finally { setBusy(false); setPreparingPhotos(false); }
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

  const shareToRoom = async (roomId) => {
    if (!sharingPostId || shareBusy) return;
    setShareBusy(true);
    try {
      await socialApi.sharePost(sharingPostId, roomId);
      setSharingPostId(null);
      toast.success("Post shared to chat.");
    } catch (cause) { toast.error(errorMessage(cause, "Couldn't share this post to that chat.")); }
    finally { setShareBusy(false); }
  };

  return (
    <section className="social-feed" aria-label="Social posts">
      <header className="social-feed__heading"><div><h2>Posts</h2><p>Persistent updates. Stories stay separate and expire after 24 hours.</p></div></header>
      <nav className="social-feed__tabs" aria-label="Post feed"><button type="button" className={scope === "all" ? "is-active" : ""} onClick={() => { setLoading(true); setScope("all"); }}>All posts</button><button type="button" className={scope === "following" ? "is-active" : ""} onClick={() => { setLoading(true); setScope("following"); }}>Following</button><button type="button" className={scope === "saved" ? "is-active" : ""} onClick={() => { setLoading(true); setScope("saved"); }}>Saved</button>{hashtagFilter ? <button type="button" className="is-active" onClick={() => setHashtagFilter("")}>#{hashtagFilter} <X size={14} /></button> : null}</nav>
      {followRequests.length ? <section className="social-follow-requests" aria-label="Follow requests"><h3><UserPlus size={17} /> Follow requests <span>{followRequests.length}</span></h3>{followRequests.map((request) => <div key={request.id} className="social-follow-requests__row"><PresenceAvatar user={request.user} src={request.user?.profile?.profile_picture} name={request.user?.profile?.display_name || request.user?.public_id || "Member"} size={36} /><span>{request.user?.profile?.display_name || request.user?.public_id || "Member"}</span><button type="button" aria-label="Accept follow request" disabled={requestsBusy} onClick={() => answerFollow(request, "accept")}><Check size={17} /></button><button type="button" aria-label="Decline follow request" disabled={requestsBusy} onClick={() => answerFollow(request, "decline")}><X size={17} /></button></div>)}</section> : null}
      <form className="social-compose" onSubmit={publish}>
        <div className="social-compose__row"><Avatar src={me?.profile?.profile_picture} name={me?.profile?.display_name} size={40} /><textarea value={text} onChange={(event) => setText(event.target.value)} maxLength={2000} rows={3} placeholder="What's on your mind?" aria-label="Post text" disabled={busy} /></div>
        {uploads.length ? <div className="social-compose__files">{uploads.map((file, index) => <div className="social-compose__file" key={`${file.name}-${file.lastModified}-${index}`}>{file.name}<button type="button" onClick={() => setUploads((current) => current.filter((_, itemIndex) => itemIndex !== index))} aria-label={`Remove ${file.name}`} disabled={busy}>×</button></div>)}</div> : null}
        <footer><label className="social-compose__image"><ImageIcon size={18} /> Photo or video<input type="file" accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime,video/webm" multiple disabled={busy} onChange={(event) => { const selected = Array.from(event.target.files || []); event.target.value = ""; if (!selected.length) return; const next = [...uploads, ...selected]; const fileError = validatePostFiles(next); if (fileError) toast.error(fileError); else setUploads(next); }} /></label>{uploads.some((file) => SOCIAL_IMAGE_EXTENSIONS.has(file.name.split(".").pop().toLowerCase())) ? <label className="social-compose__optimize"><input type="checkbox" checked={optimizePhotos} onChange={(event) => setOptimizePhotos(event.target.checked)} disabled={busy} /> Optimize large photos</label> : null}<select value={visibility} onChange={(event) => setVisibility(event.target.value)} aria-label="Post audience" disabled={busy}><option value="CONTACTS">My contacts</option><option value="FOLLOWERS">Followers</option><option value="EVERYONE">Public</option></select><button className="btn btn--primary" type="submit" disabled={busy || (!text.trim() && !uploads.length)}>{busy ? <Spinner size={16} /> : "Post"}</button></footer>
        {busy ? <div className="social-compose__progress" role="status" aria-live="polite">{preparingPhotos ? "Preparing photos…" : `Uploading… ${uploadProgress}%`}<progress max="100" value={preparingPhotos ? undefined : uploadProgress} /></div> : null}
      </form>
      {loading ? <div className="list-loading"><Spinner /></div> : error ? <div className="social-feed__error">{error} <button type="button" onClick={load}>Retry</button></div> : posts.length ? <><div className="social-feed__list" ref={feedListRef}>{posts.map((post) => <PostCard key={post.id} post={post} me={me} onChange={load} onHashtag={(tag) => { setScope("all"); setHashtagFilter(tag); setLoading(true); }} />)}</div>{hasMore ? <button className="social-feed__more" type="button" disabled={loadingMore} onClick={loadMore}>{loadingMore ? <Spinner size={16} /> : "Load more posts"}</button> : null}</> : <EmptyState text={hashtagFilter ? `No posts found for #${hashtagFilter}.` : scope === "saved" ? "You have no saved posts yet." : scope === "following" ? "No posts from followed accounts yet." : "No posts yet. Share the first update with your contacts."} />}
      {sharingPostId ? <div className="social-share-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !shareBusy) setSharingPostId(null); }}><section className="social-share-dialog" role="dialog" aria-modal="true" aria-labelledby="social-share-title"><header><h3 id="social-share-title">Share to chat</h3><button type="button" aria-label="Close share dialog" disabled={shareBusy} onClick={() => setSharingPostId(null)}><X size={18} /></button></header><div>{Object.values(rooms).filter((room) => !room.isArchived).map((room) => <button key={room.id} type="button" className="social-share-dialog__room" disabled={shareBusy} onClick={() => shareToRoom(room.id)}><Avatar src={room.isGroup ? room.groupPhoto : room.otherUser?.profile?.profile_picture} name={roomTitle(room, contactMap, me)} group={room.isGroup} size={38} /><span>{roomTitle(room, contactMap, me)}</span>{shareBusy ? <Spinner size={15} /> : <Send size={15} />}</button>)}</div>{!Object.values(rooms).some((room) => !room.isArchived) ? <EmptyState text="No chats available." /> : null}<p>The post is shared only if everyone in the chat can view it.</p></section></div> : null}
    </section>
  );
}
