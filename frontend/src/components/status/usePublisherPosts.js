import { useEffect, useState } from "react";
import { newsApi } from "../../api/endpoints";

const PUBLISHER_CACHE_MS = 5 * 60 * 1000;
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
        const available = (result.items || []).filter((item) => item.title && secureUrl(item.url));
        const latestVideo = available.find((item) => item.media_type === "VIDEO");
        const selected = latestVideo ? [available[0], latestVideo, ...available.slice(1)] : available;
        const seen = new Set();
        const items = selected.filter((item) => {
          if (!item) return false;
          const id = item.id || item.url;
          if (!id || seen.has(id)) return false;
          seen.add(id);
          return true;
        }).slice(0, 6);
        publisherCache = { expiresAt: Date.now() + PUBLISHER_CACHE_MS, items };
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
    getPublisherItems().then((nextItems) => { if (active) setItems(nextItems); })
      .catch(() => { if (active) setItems([]); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [enabled]);

  return { items, loading };
}
