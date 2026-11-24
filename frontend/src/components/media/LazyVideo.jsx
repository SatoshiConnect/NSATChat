import { useCallback, useEffect, useRef, useState } from "react";
import { readOfflineVideoPoster, writeOfflineVideoPoster } from "../../services/offlineCache";
import { useStore } from "../../store/store";

/** Attach a video URL only when its preview approaches the viewport. */
export default function LazyVideo({ src, preload = "metadata", onPosterAvailable, ...props }) {
  const ref = useRef(null);
  const userId = useStore((state) => state.me?.id);
  const [savedPoster, setSavedPoster] = useState(null);
  const mediaPath = (() => {
    try { return new URL(src, window.location.origin).pathname; } catch { return ""; }
  })();
  const canSavePoster = /^\/media\/chat\/attachments\//i.test(mediaPath);
  const posterKey = `${userId || 0}:${src || ""}`;

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    if (canSavePoster && userId) {
      readOfflineVideoPoster(userId, src).then((blob) => {
        if (!active || !blob) return;
        objectUrl = URL.createObjectURL(blob);
        setSavedPoster({ key: posterKey, url: objectUrl });
        onPosterAvailable?.();
      });
    }
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [canSavePoster, onPosterAvailable, posterKey, src, userId]);

  const savePoster = useCallback(() => {
    const video = ref.current;
    if (!canSavePoster || !userId || !video || video.readyState < 2 || !video.videoWidth) return;
    const scale = Math.min(1, 640 / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const context = canvas.getContext("2d");
    if (!context) return;
    try {
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        if (blob) writeOfflineVideoPoster(userId, src, blob);
      }, "image/webp", 0.7);
    } catch {
      // A browser may block canvas extraction for media that is not same-origin.
    }
  }, [canSavePoster, src, userId]);

  const onLoadedData = (event) => {
    savePoster();
    props.onLoadedData?.(event);
  };

  useEffect(() => {
    const video = ref.current;
    if (!video || !src) return undefined;
    let attached = false;
    const attach = () => {
      if (attached || !video.isConnected) return;
      attached = true;
      video.preload = preload;
      video.src = src;
    };

    if (!("IntersectionObserver" in window)) {
      attach();
      return undefined;
    }

    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer.disconnect();
        attach();
      }
    }, { rootMargin: "300px 0px" });
    observer.observe(video);
    return () => observer.disconnect();
  }, [preload, src]);

  const offlinePoster = savedPoster?.key === posterKey ? savedPoster.url : "";
  return <video {...props} ref={ref} poster={props.poster || offlinePoster || undefined} onLoadedData={onLoadedData} loading="lazy" preload="none" />;
}
