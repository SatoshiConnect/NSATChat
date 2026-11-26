import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Eye, Flag, Gift, MoreVertical, Pause, Pencil, Play, Send, Share2, Trash2, UserCheck, UserPlus, Volume2, VolumeX, X } from "lucide-react";
import { errorMessage, mediaUrl } from "../../api/client";
import { marketplaceApi, socialApi, statusApi } from "../../api/endpoints";
import { loadStatus } from "../../store/actions";
import { dispatch, getState, useStore } from "../../store/store";
import { toast } from "../../services/toast";
import { detailTime, listTime } from "../../utils/format";
import { contactsByUser, displayUserName, roomTitle } from "../../utils/messages";
import { Avatar, EmptyState, IconButton, MenuButton, Modal, Spinner } from "../common/ui";
import PresenceAvatar from "../common/PresenceAvatar";
import { confirmAction } from "../common/dialogs";
import { useApp } from "../layout/AppContext";
import StatusReplyBar from "./StatusReplyBar";
import "../../styles/status-media-errors.css";

const IMAGE_MS = 6000;

/** Mark a status seen locally so the ring/dot update immediately. */
function markSeenLocally(statusId) {
  const state = getState();
  const feed = state.statusFeed.map((group) => {
    let changed = false;
    const statuses = group.statuses.map((status) => {
      if (status.id !== statusId || status.is_viewed) return status;
      changed = true;
      return { ...status, is_viewed: true };
    });
    return changed ? { ...group, statuses, unseen_count: statuses.filter((s) => !s.is_viewed).length } : group;
  });
  dispatch({ type: "status/set", feed, mine: state.myStatuses });
}

/** "Viewed by" sheet shown inside the viewer (the status stays paused while it's open). */
function ViewersSheet({ statusId, count, onClose }) {
  const contacts = useStore((state) => state.contacts);
  const contactMap = useMemo(() => contactsByUser(contacts), [contacts]);
  const [result, setResult] = useState({ key: "", rows: null });
  const key = `${statusId}:${count}`;
  useEffect(() => {
    let cancelled = false;
    statusApi
      .viewers(statusId)
      .then((rows) => !cancelled && setResult({ key, rows: Array.isArray(rows) ? rows : rows?.results || [] }))
      .catch((error) => {
        if (cancelled) return;
        toast.error(errorMessage(error));
        setResult({ key, rows: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [statusId, key]);
  const rows = result.rows;
  return (
    <div className="status-sheet" role="dialog" aria-label="Viewed by" onPointerDown={(event) => event.stopPropagation()}>
      <header className="status-sheet__head">
        <strong>Viewed by {rows ? rows.length : count ?? ""}</strong>
        <IconButton icon={X} label="Close viewers" onClick={onClose} />
      </header>
      <div className="status-sheet__list">
        {!rows ? <div className="list-loading"><Spinner /></div> : null}
        {rows && !rows.length ? <p className="status-sheet__empty">No views yet</p> : null}
        {rows?.map((row) => (
          <div key={row.id} className="row row--static">
            <PresenceAvatar user={row.viewer} src={row.viewer?.profile?.profile_picture} name={displayUserName(row.viewer, contactMap)} size={40} />
            <span className="row__body">
              <span className="row__title">{displayUserName(row.viewer, contactMap)}</span>
              <span className="row__subtitle">{detailTime(row.viewed_at)}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Full-screen status viewer with progress bars, auto-advance, pause on hold,
 * reactions/replies for others' statuses and viewers/delete for your own.
 */
export default function StatusViewer({ groups, startGroup = 0, startStatusId, onClose }) {
  const app = useApp();
  const me = useStore((state) => state.me);
  const contacts = useStore((state) => state.contacts);
  const rooms = useStore((state) => state.rooms);
  const contactMap = useMemo(() => contactsByUser(contacts), [contacts]);
  const [groupIndex, setGroupIndex] = useState(startGroup);
  const group = groups[groupIndex];
  const firstUnseen = Math.max(0, group?.statuses.findIndex((status) => !status.is_viewed));
  const requested = startStatusId ? group?.statuses.findIndex((status) => Number(status.id) === Number(startStatusId)) : -1;
  const [index, setIndex] = useState(requested >= 0 ? requested : firstUnseen);
  const [progress, setProgress] = useState(0);
  const [paused, setPaused] = useState(false);
  const [muted, setMuted] = useState(false);
  const [viewers, setViewers] = useState(null);
  const [mediaOverrides, setMediaOverrides] = useState({});
  const [mediaUnavailable, setMediaUnavailable] = useState({});
  const mediaRefreshAttempts = useRef(new Set());
  const [giftItems, setGiftItems] = useState(null);
  const [giftMode, setGiftMode] = useState("simulation");
  const [giftBusy, setGiftBusy] = useState(false);
  const [giftAnimation, setGiftAnimation] = useState(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [reportReason, setReportReason] = useState("SPAM");
  const [reportDetails, setReportDetails] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [editBusy, setEditBusy] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [editBackground, setEditBackground] = useState("#075E54");
  const [followState, setFollowState] = useState(null);
  const [followBusy, setFollowBusy] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [shareBusy, setShareBusy] = useState(false);
  const videoRef = useRef(null);
  const swipeStart = useRef(null);
  const status = group?.statuses[index];
  const isMine = Number(group?.user?.id) === Number(me.id);
  const liveViews = useStore((state) => (isMine && status ? state.myStatuses.find((item) => item.id === status.id)?.views_count : undefined));
  const viewsCount = liveViews ?? status?.views_count ?? 0;
  const owner = group?.user;
  const ownerName = isMine ? "My status" : displayUserName(owner, contactMap);
  const currentFollow = followState?.ownerId === Number(owner?.id) ? followState : null;

  useEffect(() => {
    if (!owner?.id || isMine) return undefined;
    let active = true;
    socialApi.followStatus(owner.id).then((value) => {
      if (active) setFollowState({ ...value, ownerId: Number(owner.id) });
    }).catch(() => {
      if (active) setFollowState({ unavailable: true, ownerId: Number(owner.id) });
    });
    return () => { active = false; };
  }, [owner?.id, isMine]);

  const toggleFollow = async () => {
    if (!owner?.id || followBusy || !currentFollow || currentFollow.unavailable) return;
    setFollowBusy(true);
    try {
      if (currentFollow.following || currentFollow.request_pending) {
        await socialApi.unfollow(owner.id);
        await loadStatus();
        toast.success("Follow removed.");
        onClose();
        return;
      }
      const next = await socialApi.follow(owner.id);
      setFollowState({ ...next, ownerId: Number(owner.id) });
      await loadStatus();
      toast.success(next.request_pending ? "Follow request sent." : "Following this account.");
    } catch (error) { toast.error(errorMessage(error, "Couldn't update follow status.")); }
    finally { setFollowBusy(false); }
  };

  // A live marketplace sells gifts as paid orders addressed to the Story
  // owner; a demo deployment still records the free simulation instead.
  const openGiftPicker = async () => {
    setPaused(true);
    try {
      const config = await marketplaceApi.config();
      if (config?.live_payments) {
        const catalog = await marketplaceApi.catalog({ kind: "gift" });
        setGiftMode("paid");
        setGiftItems(catalog.filter((item) => item.purchase_mode === "nsat"));
        return;
      }
      const inventory = await marketplaceApi.inventory();
      setGiftMode("simulation");
      setGiftItems(inventory.filter((entry) => entry.item?.kind === "gift"));
    } catch (error) {
      toast.error(errorMessage(error));
      setPaused(false);
    }
  };

  const giftError = (error) => {
    const messages = {
      recipient_already_owns: `${ownerName || "They"} already owns this gift.`,
      gift_status_expired: "This update has expired. Open a newer Story to send a gift.",
      gift_status_not_visible: "You can only gift an update you can see.",
      gift_status_not_recipients: "That Story does not belong to this person.",
      cannot_gift_to_self: "You cannot send a gift to yourself.",
      cannot_gift_to_creator: "The creator already owns this listing.",
      wallet_not_linked: "Connect your NSAT wallet in the Wallet tab first.",
      order_already_open: "You already have an open order for this gift. Continue it from the marketplace banner.",
      marketplace_payments_unavailable: "Marketplace payments are paused right now.",
      gift_is_paid: "Gifts are paid in NSAT through checkout.",
    };
    return messages[error?.response?.data?.code] || errorMessage(error);
  };

  const sendGift = async (entry) => {
    if (!status || !owner) return;
    setGiftBusy(true);
    try {
      if (giftMode === "paid") {
        const order = await marketplaceApi.createOrder(entry.id, crypto.randomUUID(), {
          recipient_id: owner.id,
          status_id: status.id,
        });
        setGiftItems(null);
        onClose();
        toast.success(`Checkout opened. ${ownerName} gets this gift once the payment confirms.`);
        app.openWallet({ orderId: order.id });
        return;
      }
      const result = await marketplaceApi.sendGift({ item_id: entry.item.id, recipient_id: owner.id, status_id: status.id });
      toast.success(result.message || "Gift simulation recorded.");
      setGiftAnimation({ title: entry.item.title, paid: false });
      setGiftItems(null);
      setPaused(false);
    } catch (error) { toast.error(giftError(error)); }
    finally { setGiftBusy(false); }
  };

  const submitReport = async (event) => {
    event.preventDefault();
    if (!status || reportBusy) return;
    setReportBusy(true);
    try {
      const result = await statusApi.report(status.id, { reason: reportReason, details: reportDetails.trim() });
      setReportOpen(false);
      setReportDetails("");
      setPaused(false);
      toast.success(result.already_reported ? "You already reported this status." : "Status sent to moderators for review.");
    } catch (error) {
      toast.error(errorMessage(error, "Couldn't report this status."));
    } finally {
      setReportBusy(false);
    }
  };

  const submitEdit = async (event) => {
    event.preventDefault();
    if (!status || editBusy) return;
    setEditBusy(true);
    try {
      const payload = { content: editContent.trim() };
      if (status.status_type === "TEXT") payload.background_color = editBackground;
      await statusApi.edit(status.id, payload);
      await loadStatus();
      toast.success("Status updated.");
      setEditOpen(false);
      setPaused(false);
      onClose();
    } catch (error) {
      toast.error(errorMessage(error, "Couldn't update this status."));
    } finally {
      setEditBusy(false);
    }
  };

  const shareToRoom = async (roomId) => {
    if (!status || shareBusy) return;
    setShareBusy(true);
    try {
      await statusApi.share(status.id, roomId);
      setShareOpen(false);
      setPaused(false);
      toast.success("Status shared to chat.");
    } catch (error) {
      toast.error(errorMessage(error, "Couldn't share this status to that chat."));
    } finally {
      setShareBusy(false);
    }
  };

  const next = useCallback(() => {
    setProgress(0);
    if (index < group.statuses.length - 1) setIndex(index + 1);
    else if (groupIndex < groups.length - 1) {
      const nextGroup = groups[groupIndex + 1];
      setGroupIndex(groupIndex + 1);
      setIndex(Math.max(0, nextGroup.statuses.findIndex((s) => !s.is_viewed)));
    } else onClose();
  }, [index, group, groupIndex, groups, onClose]);

  const previous = useCallback(() => {
    setProgress(0);
    if (index > 0) setIndex(index - 1);
    else if (groupIndex > 0) {
      setGroupIndex(groupIndex - 1);
      setIndex(0);
    }
  }, [index, groupIndex]);

  const onContentPointerDown = (event) => {
    if (event.target.closest("button, input, video, .status-viewer__reply")) return;
    swipeStart.current = { x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setPaused(true);
  };
  const onContentPointerUp = (event) => {
    const start = swipeStart.current;
    swipeStart.current = null;
    if (start && Math.abs(event.clientX - start.x) > 64 && Math.abs(event.clientX - start.x) > Math.abs(event.clientY - start.y)) {
      setProgress(0);
      if (event.clientX < start.x && groupIndex < groups.length - 1) {
        const nextGroupIndex = groupIndex + 1;
        setGroupIndex(nextGroupIndex);
        setIndex(Math.max(0, groups[nextGroupIndex].statuses.findIndex((item) => !item.is_viewed)));
      } else if (event.clientX > start.x && groupIndex > 0) {
        const previousGroupIndex = groupIndex - 1;
        setGroupIndex(previousGroupIndex);
        setIndex(Math.max(0, groups[previousGroupIndex].statuses.findIndex((item) => !item.is_viewed)));
      }
    }
    setPaused(false);
  };

  // Record the view (server) and update the ring locally.
  useEffect(() => {
    if (!status || isMine || status.is_viewed) return;
    markSeenLocally(status.id);
    statusApi.view(status.id).catch(() => {});
  }, [status, isMine]);

  // Timer for images/text; videos advance on "ended".
  useEffect(() => {
    if (!status || paused || status.status_type === "VIDEO") return undefined;
    const started = Date.now() - progress * IMAGE_MS;
    const timer = window.setInterval(() => {
      const value = (Date.now() - started) / IMAGE_MS;
      if (value >= 1) {
        window.clearInterval(timer);
        next();
      } else setProgress(value);
    }, 50);
    return () => window.clearInterval(timer);
    // progress is read once when (re)starting
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, paused, next]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (paused) video.pause();
    else video.play().catch(() => {});
  }, [paused, status]);

  useEffect(() => {
    if (!giftAnimation) return undefined;
    const timer = window.setTimeout(() => setGiftAnimation(""), 1800);
    return () => window.clearTimeout(timer);
  }, [giftAnimation]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.target.tagName === "INPUT") return;
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowRight") next();
      if (event.key === "ArrowLeft") previous();
      if (event.key === " ") setPaused((value) => !value);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [next, previous, onClose]);

  if (!group || !status) return null;

  function remove() {
    setPaused(true);
    confirmAction({
      title: "Delete this status update?",
      message: "It will be deleted for everyone who received it.",
      confirmLabel: "Delete",
      danger: true,
      onConfirm: async () => {
        try {
          await statusApi.remove(status.id);
          await loadStatus();
          toast("Status deleted");
          onClose();
        } catch (error) {
          toast.error(errorMessage(error));
        }
      },
    });
  }

  const media = mediaUrl(mediaOverrides[status.id] || status.media);
  const refreshStatusMedia = async () => {
    if (mediaRefreshAttempts.current.has(status.id)) {
      setMediaUnavailable((current) => ({ ...current, [status.id]: true }));
      return;
    }
    mediaRefreshAttempts.current.add(status.id);
    await loadStatus();
    const state = getState();
    const freshStatus = [...state.myStatuses, ...state.statusFeed.flatMap((item) => item.statuses || [])]
      .find((item) => Number(item.id) === Number(status.id));
    if (freshStatus?.media && freshStatus.media !== status.media) {
      setMediaOverrides((current) => ({ ...current, [status.id]: freshStatus.media }));
      return;
    }
    setMediaUnavailable((current) => ({ ...current, [status.id]: true }));
  };

  return createPortal(
    <div className="status-viewer" role="dialog" aria-label={`${ownerName} status`}>
      <div className="status-viewer__frame">
        <div className="status-viewer__bars">
          {group.statuses.map((item, itemIndex) => (
            <span key={item.id}>
              <span style={{ width: `${itemIndex < index ? 100 : itemIndex === index ? progress * 100 : 0}%` }} />
            </span>
          ))}
        </div>
        <header className="status-viewer__top">
          <PresenceAvatar user={owner} src={owner?.profile?.profile_picture} name={ownerName} size={40} />
          <div className="status-viewer__who">
            <strong>{ownerName}</strong>
            <span>{listTime(status.created_at)}</span>
          </div>
          <IconButton icon={paused ? Play : Pause} label={paused ? "Play" : "Pause"} onClick={() => setPaused((value) => !value)} />
          {status.status_type === "VIDEO" ? <IconButton icon={muted ? VolumeX : Volume2} label={muted ? "Unmute" : "Mute"} onClick={() => setMuted((value) => !value)} /> : null}
          {isMine ? (
            <span onClickCapture={() => setPaused(true)}>
              <MenuButton
                icon={MoreVertical}
                label="Status options"
                items={[
                  { label: `Viewed by ${viewsCount}`, icon: Eye, onClick: () => setViewers(status.id) },
                  { label: "Edit status", icon: Pencil, onClick: () => { setEditContent(status.content || ""); setEditBackground(/^#[0-9a-f]{6}$/i.test(status.background_color || "") ? status.background_color : "#075E54"); setEditOpen(true); } },
                  { label: "Delete", icon: Trash2, danger: true, onClick: remove },
                ]}
              />
            </span>
          ) : (
            <span onClickCapture={() => setPaused(true)}>
              <MenuButton
                icon={MoreVertical}
                label="Status options"
                items={[
                  !currentFollow?.unavailable && { label: currentFollow?.following ? "Unfollow account" : currentFollow?.request_pending ? "Cancel follow request" : "Follow account", icon: currentFollow?.following || currentFollow?.request_pending ? UserCheck : UserPlus, disabled: followBusy || !currentFollow, onClick: toggleFollow },
                  { label: "Report status", icon: Flag, danger: true, onClick: () => setReportOpen(true) },
                ].filter(Boolean)}
              />
            </span>
          )}
          <IconButton icon={X} label="Close" onClick={onClose} />
        </header>

        <div
          className="status-viewer__content"
          style={status.status_type === "TEXT" ? { background: status.background_color, color: status.text_color } : undefined}
          onPointerDown={onContentPointerDown}
          onPointerUp={onContentPointerUp}
          onPointerCancel={onContentPointerUp}
        >
          {status.status_type === "TEXT" ? <p className="status-viewer__text">{status.content}</p> : null}
          {status.status_type === "IMAGE" ? (mediaUnavailable[status.id] ? <p className="status-viewer__media-error" role="status">Couldn't load this photo. Check your connection and reopen the story.</p> : <img src={media} alt="Status" onError={refreshStatusMedia} />) : null}
          {status.status_type === "VIDEO" ? (
            mediaUnavailable[status.id]
              ? <p className="status-viewer__media-error" role="status">Couldn't load this video. Check your connection and reopen the story.</p>
              : <video
                ref={videoRef}
                src={media}
                autoPlay
                playsInline
                muted={muted}
                onTimeUpdate={(event) => event.currentTarget.duration && setProgress(event.currentTarget.currentTime / event.currentTarget.duration)}
                onEnded={next}
                onError={refreshStatusMedia}
              />
          ) : null}
          {status.status_type !== "TEXT" && status.content ? <p className="status-viewer__caption">{status.content}</p> : null}
        </div>

        <button type="button" className="status-viewer__nav status-viewer__nav--prev" onClick={previous} aria-label="Previous status" disabled={index === 0 && groupIndex === 0}>
          <ChevronLeft size={28} />
        </button>
        <button type="button" className="status-viewer__nav status-viewer__nav--next" onClick={next} aria-label="Next status">
          <ChevronRight size={28} />
        </button>

        {viewers ? <ViewersSheet statusId={viewers} count={viewsCount} onClose={() => { setViewers(null); setPaused(false); }} /> : null}

        {reportOpen ? <Modal
          title="Report status"
          onClose={reportBusy ? undefined : () => { setReportOpen(false); setPaused(false); }}
          footer={<><button type="button" className="btn btn--ghost" onClick={() => { setReportOpen(false); setPaused(false); }} disabled={reportBusy}>Cancel</button><button type="submit" form="status-report-form" className="btn btn--primary" disabled={reportBusy}>{reportBusy ? <Spinner size={16} /> : "Send report"}</button></>}
        >
          <form id="status-report-form" className="status-report-form" onSubmit={submitReport}>
            <label>Reason<select value={reportReason} onChange={(event) => setReportReason(event.target.value)}><option value="SPAM">Spam or misleading</option><option value="HARASSMENT">Harassment</option><option value="HATE">Hate or abusive content</option><option value="SEXUAL">Sexual content</option><option value="VIOLENCE">Violence or dangerous content</option><option value="SCAM">Scam or fraud</option><option value="OTHER">Other</option></select></label>
            <label>Details (optional)<textarea value={reportDetails} onChange={(event) => setReportDetails(event.target.value)} maxLength={1000} rows={3} /></label>
          </form>
        </Modal> : null}

        {editOpen ? <Modal
          title="Edit status"
          onClose={editBusy ? undefined : () => { setEditOpen(false); setPaused(false); }}
          footer={<><button type="button" className="btn btn--ghost" onClick={() => { setEditOpen(false); setPaused(false); }} disabled={editBusy}>Cancel</button><button type="submit" form="status-edit-form" className="btn btn--primary" disabled={editBusy || (status.status_type === "TEXT" && !editContent.trim())}>{editBusy ? <Spinner size={16} /> : "Save changes"}</button></>}
        >
          <form id="status-edit-form" className="status-report-form" onSubmit={submitEdit}>
            <label>{status.status_type === "TEXT" ? "Text" : "Caption"}<textarea value={editContent} onChange={(event) => setEditContent(event.target.value)} maxLength={700} rows={4} autoFocus /></label>
            {status.status_type === "TEXT" ? <label>Background color<input type="color" value={editBackground} onChange={(event) => setEditBackground(event.target.value)} /></label> : null}
          </form>
        </Modal> : null}

        {shareOpen ? <Modal title="Share status to chat" onClose={shareBusy ? undefined : () => { setShareOpen(false); setPaused(false); }}>
          <div className="status-share-list">
            {Object.values(rooms).filter((room) => !room.isArchived).map((room) => (
              <button key={room.id} type="button" className="status-share-list__room" disabled={shareBusy} onClick={() => shareToRoom(room.id)}>
                <Avatar src={room.isGroup ? room.groupPhoto : room.otherUser?.profile?.profile_picture} name={roomTitle(room, contactMap, me)} group={room.isGroup} size={38} />
                <span>{roomTitle(room, contactMap, me)}</span>
                {shareBusy ? <Spinner size={15} /> : <Send size={15} />}
              </button>
            ))}
            {!Object.values(rooms).some((room) => !room.isArchived) ? <EmptyState text="No chats available." /> : null}
          </div>
          <p className="info-muted">The chat receives a status link only if every member can view it.</p>
        </Modal> : null}

        <footer className="status-viewer__bottom" hidden={Boolean(viewers)}>
          {isMine ? (
            <button type="button" className="status-viewer__views" onClick={() => { setPaused(true); setViewers(status.id); }}>
              <Eye size={18} /> {viewsCount} view{viewsCount === 1 ? "" : "s"}
            </button>
          ) : (
            <>
              <button type="button" className="status-viewer__gift" onClick={openGiftPicker} aria-label="Send creator gift"><Gift size={19} /><span>Gift</span></button>
              <StatusReplyBar key={status.id} status={status} owner={owner} onPause={() => setPaused(true)} onResume={() => setPaused(false)} />
            </>
          )}
          <button type="button" className="status-viewer__share" onClick={() => { setPaused(true); setShareOpen(true); }} aria-label="Share status to chat"><Share2 size={19} /><span>Share</span></button>
        </footer>
        {giftItems ? <div className="status-gift-picker" role="dialog" aria-label="Choose a gift">
          <div className="status-gift-picker__head"><strong>Choose a gift</strong><IconButton icon={X} label="Close gift picker" onClick={() => { setGiftItems(null); setPaused(false); }} /></div>
          {giftMode === "paid"
            ? <p>Pay in NSAT. {ownerName} gets it in their library once the network confirms the payment.</p>
            : <p>Gift simulation only. No NSAT will be transferred.</p>}
          {giftItems.length ? giftItems.map((entry) => {
            const item = giftMode === "paid" ? entry : entry.item;
            return (
              <button type="button" key={giftMode === "paid" ? item.id : entry.id} disabled={giftBusy} onClick={() => sendGift(entry)}>
                <Gift size={18} /><span>{item.title}</span>
                <small>{giftMode === "paid" ? `${Number(item.proposed_price_nsat).toLocaleString()} NSAT` : "Use from library"}</small>
              </button>
            );
          }) : <p>{giftMode === "paid" ? "No gifts are for sale right now." : "Your library has no gifts yet. Get a gift from Creator marketplace first."}</p>}
        </div> : null}
        {giftAnimation ? <div className="status-gift-animation" aria-live="polite"><Gift size={34} /><strong>{giftAnimation.title}</strong><span>{giftAnimation.paid ? "Gift sent · paid in NSAT" : "Gift sent · simulation only"}</span></div> : null}
      </div>
    </div>,
    document.body,
  );
}
