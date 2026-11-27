import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronLeft, ChevronRight, Download, Forward, Maximize2, MessageSquareReply, X } from "lucide-react";
import { mediaUrl } from "../../api/client";
import { detailTime } from "../../utils/format";
import { attachmentKind } from "../../utils/messages";
import { OFFLINE_VIDEO_MAX_FILE, readOfflineVideo, writeOfflineVideo } from "../../services/offlineCache";
import { toast } from "../../services/toast";
import { useStore } from "../../store/store";
import { Avatar, IconButton } from "../common/ui";

/**
 * Full-screen media viewer for a conversation's photos and videos with
 * previous/next navigation (arrows, keyboard, thumbnails), download,
 * forward and "go to message".
 */
export default function Lightbox({ items, startIndex = 0, nameOf, onClose, onForward, onGoTo }) {
  const [index, setIndex] = useState(startIndex);
  const userId = useStore((state) => state.me?.id);
  const [offlineVideo, setOfflineVideo] = useState(null);
  const [savingOffline, setSavingOffline] = useState(false);
  const localObjectUrl = useRef("");
  const videoRef = useRef(null);
  const stripRef = useRef(null);
  const current = items[index];
  const kind = attachmentKind(current?.attachment);
  const url = current?.attachment ? mediaUrl(current.attachment.file) : "";
  const mediaKey = `${userId || 0}:${url}`;
  // Swipe left / right to see the next or previous photo (phones and touchpads).
  const swipe = useRef(null);
  const [dragX, setDragX] = useState(0);

  const go = useCallback((step) => setIndex((value) => Math.min(items.length - 1, Math.max(0, value + step))), [items.length]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowRight") go(1);
      if (event.key === "ArrowLeft") go(-1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [go, onClose]);

  useEffect(() => {
    stripRef.current?.querySelector(".is-active")?.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
  }, [index]);

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    if (kind === "video" && userId && url) {
      readOfflineVideo(userId, url).then((blob) => {
        if (!active || !blob) return;
        objectUrl = URL.createObjectURL(blob);
        setOfflineVideo({ key: mediaKey, url: objectUrl });
      });
    }
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      if (localObjectUrl.current) {
        URL.revokeObjectURL(localObjectUrl.current);
        localObjectUrl.current = "";
      }
    };
  }, [kind, mediaKey, url, userId]);

  if (!current) return null;
  const localVideoUrl = offlineVideo?.key === mediaKey ? offlineVideo.url : "";
  const sender = current.message.sender;

  const saveVideoOffline = async () => {
    if (savingOffline || localVideoUrl) return;
    setSavingOffline(true);
    try {
      const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error("Couldn't download this video for offline viewing.");
      const type = (response.headers.get("content-type") || "").split(";")[0].trim();
      if (!type.startsWith("video/")) throw new Error("This file is not a supported video.");
      const statedSize = Number(response.headers.get("content-length") || 0);
      if (statedSize > OFFLINE_VIDEO_MAX_FILE) throw new Error("Videos over 20 MB can't be saved offline.");
      let blob;
      if (response.body?.getReader) {
        const reader = response.body.getReader();
        const chunks = [];
        let size = 0;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > OFFLINE_VIDEO_MAX_FILE) {
            await reader.cancel();
            throw new Error("Videos over 20 MB can't be saved offline.");
          }
          chunks.push(value);
        }
        blob = new Blob(chunks, { type });
      } else {
        blob = await response.blob();
      }
      if (blob.size > OFFLINE_VIDEO_MAX_FILE) throw new Error("Videos over 20 MB can't be saved offline.");
      if (!await writeOfflineVideo(userId, url, blob)) throw new Error("This browser couldn't save the video on this device.");
      const objectUrl = URL.createObjectURL(blob);
      localObjectUrl.current = objectUrl;
      setOfflineVideo({ key: mediaKey, url: objectUrl });
      toast.success("Video saved for offline viewing on this device.");
    } catch (error) {
      toast.error(error.message || "Couldn't save the video for offline viewing.");
    } finally {
      setSavingOffline(false);
    }
  };

  return createPortal(
    <div className="lightbox" role="dialog" aria-label="Media viewer">
      <header className="lightbox__top">
        <Avatar src={sender?.profile?.profile_picture} name={nameOf(sender?.id)} size={40} />
        <div className="lightbox__who">
          <strong>{nameOf(sender?.id)}</strong>
          <span>{detailTime(current.message.created_at)}</span>
        </div>
        <div className="lightbox__actions">
          {onGoTo ? <IconButton icon={MessageSquareReply} label="Go to message" onClick={() => { onGoTo(current.message); onClose(); }} /> : null}
          {onForward ? <IconButton icon={Forward} label="Forward" onClick={() => onForward(current.message)} /> : null}
          {kind === "video" ? <IconButton icon={localVideoUrl ? Check : Download} label={localVideoUrl ? "Saved for offline" : savingOffline ? "Saving video offline" : "Save video offline"} disabled={savingOffline || Boolean(localVideoUrl)} onClick={saveVideoOffline} /> : null}
          <a className="icon-btn" href={url} download={current.attachment.file_name || true} target="_blank" rel="noopener noreferrer" aria-label="Download" data-tooltip="Download">
            <Download size={20} />
          </a>
          {kind === "video" ? <IconButton icon={Maximize2} label="Full screen" onClick={() => videoRef.current?.requestFullscreen?.()} /> : null}
          <IconButton icon={X} label="Close" onClick={onClose} />
        </div>
      </header>

      <div
        className="lightbox__stage"
        onClick={(event) => event.target === event.currentTarget && !swipe.current?.moved && onClose()}
        onPointerDown={(event) => {
          if (event.pointerType === "mouse" || event.target.closest("button, video")) return;
          swipe.current = { x: event.clientX, y: event.clientY, moved: false };
        }}
        onPointerMove={(event) => {
          const start = swipe.current;
          if (!start) return;
          const dx = event.clientX - start.x;
          if (!start.moved && (Math.abs(dx) < 8 || Math.abs(dx) < Math.abs(event.clientY - start.y))) return;
          start.moved = true;
          const atEdge = (dx > 0 && index === 0) || (dx < 0 && index === items.length - 1);
          setDragX(atEdge ? dx / 4 : dx);
        }}
        onPointerUp={(event) => {
          const start = swipe.current;
          swipe.current = start?.moved ? { moved: true } : null;
          window.setTimeout(() => { swipe.current = null; }, 0);
          if (!start?.moved) return;
          const dx = event.clientX - start.x;
          setDragX(0);
          if (dx < -60) go(1);
          else if (dx > 60) go(-1);
        }}
        onPointerCancel={() => {
          swipe.current = null;
          setDragX(0);
        }}
      >
        {index > 0 ? (
          <button type="button" className="lightbox__nav lightbox__nav--prev" onClick={() => go(-1)} aria-label="Previous">
            <ChevronLeft size={30} />
          </button>
        ) : null}
        {kind === "video" ? (
          <ChatVideoPlayback
            key={mediaKey}
            videoRef={videoRef}
            url={url}
            cachedUrl={localVideoUrl}
            fileName={current.attachment.file_name}
          />
        ) : (
          <img
            key={url}
            src={url}
            alt={current.attachment.file_name || "Photo"}
            draggable={false}
            className={dragX ? "is-dragging" : ""}
            style={dragX ? { transform: `translateX(${dragX}px)`, opacity: Math.max(0.4, 1 - Math.abs(dragX) / 600) } : undefined}
          />
        )}
        {index < items.length - 1 ? (
          <button type="button" className="lightbox__nav lightbox__nav--next" onClick={() => go(1)} aria-label="Next">
            <ChevronRight size={30} />
          </button>
        ) : null}
      </div>
      {current.message.content ? <p className="lightbox__caption">{current.message.content}</p> : null}
      {items.length > 1 ? <p className="lightbox__count">{index + 1} of {items.length}</p> : null}

      {items.length > 1 ? (
        <div className="lightbox__strip" ref={stripRef}>
          {items.map((item, itemIndex) => {
            const itemKind = attachmentKind(item.attachment);
            return (
              <button key={`${item.message.id}-${item.attachment.id}`} type="button" className={itemIndex === index ? "is-active" : ""} onClick={() => setIndex(itemIndex)} aria-label={`Show item ${itemIndex + 1}`}>
                {itemKind === "video" ? <video src={`${mediaUrl(item.attachment.file)}#t=0.1`} muted preload="metadata" /> : <img src={mediaUrl(item.attachment.file)} alt="" loading="lazy" />}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>,
    document.body,
  );
}


// Video failures are local to this attachment, not to the whole media viewer.
function ChatVideoPlayback({ videoRef, url, cachedUrl, fileName }) {
  const [attempt, setAttempt] = useState(0);
  const [failedSource, setFailedSource] = useState(null);
  const [ignoreCache, setIgnoreCache] = useState(false);
  const source = !ignoreCache && cachedUrl ? cachedUrl : url;
  const hasFailed = failedSource === source;

  const onError = () => {
    if (source === cachedUrl && url && source !== url && navigator.onLine !== false) {
      // A stale or corrupt offline copy must not make a working server file unplayable.
      setIgnoreCache(true);
      setFailedSource(null);
      return;
    }
    setFailedSource(source);
  };

  if (hasFailed) {
    return (
      <div className="lightbox__video-error" role="alert">
        <strong>This video couldn’t be played.</strong>
        <p>Check your connection and try again. If it still won’t play, download the original.</p>
        <div className="lightbox__video-error-actions">
          <button type="button" onClick={() => { setFailedSource(null); setAttempt((n) => n + 1); }}>Try again</button>
          <a href={url} download={fileName || true} target="_blank" rel="noopener noreferrer">Download original</a>
        </div>
      </div>
    );
  }

  return <video key={`${source}:${attempt}`} ref={videoRef} src={source} controls autoPlay playsInline onError={onError} />;
}
