import { useEffect, useState } from "react";
import { newsApi } from "../../api/endpoints";

const PUBLISHER_REFRESH_MS = 10 * 60 * 1000;
let publisherCache = { expiresAt: 0, items: [] };
let publisherRequest = null;

function secureUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function getPublisherItems() {
  if (publisherCache.expiresAt > Date.now()) return Promise.resolve(publisherCache.items);
  if (!publisherRequest) {
    publisherRequest = newsApi.today()
      .then((result) => {
        const available = (result.items || [])
          .filter((item) => item.title && secureUrl(item.url) && (secureUrl(item.image_url) || (item.media_type === "VIDEO" && secureUrl(item.video_url))))
          .sort((left, right) => {
            const prominence = Number(right.interest_rating || right.coverage_count || 0) - Number(left.interest_rating || left.coverage_count || 0);
            return prominence || (Date.parse(right.published_at || "") || 0) - (Date.parse(left.published_at || "") || 0);
          });
        const latestVideo = available.find((item) => item.media_type === "VIDEO");
        const selected = latestVideo ? [latestVideo, ...available] : available;
        const seen = new Set();
        const items = selected.filter((item) => {
          if (!item) return false;
          const id = item.id || item.url;
          if (!id || seen.has(id)) return false;
          seen.add(id);
          return true;
        }).slice(0, 6);
        publisherCache = { expiresAt: Date.now() + PUBLISHER_REFRESH_MS, items };
        return items;
      })
      .finally(() => { publisherRequest = null; });
  }
  return publisherRequest;
}

export default function usePublisherPosts(enabled) {
  const [items, setItems] = useState(() => publisherCache.items);
  const [loading, setLoading] = useState(() => !publisherCache.items.length);

  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    const refresh = () => {
      getPublisherItems().then((nextItems) => { if (active) setItems(nextItems); })
        .catch(() => { if (active && !publisherCache.items.length) setItems([]); })
        .finally(() => { if (active) setLoading(false); });
    };
    const onVisibilityChange = () => { if (!document.hidden) refresh(); };
    refresh();
    const timer = window.setInterval(refresh, PUBLISHER_REFRESH_MS);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [enabled]);

  return { items, loading };
}
