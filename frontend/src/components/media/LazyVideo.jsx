import { useEffect, useRef } from "react";

/** Attach a video URL only when its preview approaches the viewport. */
export default function LazyVideo({ src, preload = "metadata", ...props }) {
  const ref = useRef(null);

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

  return <video {...props} ref={ref} loading="lazy" preload="none" />;
}
