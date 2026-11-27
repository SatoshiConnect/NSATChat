import { ArrowRight, ExternalLink, Newspaper, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { newsApi } from "../../api/endpoints";
import { useApp } from "../layout/AppContext";

const PUBLISHER_CACHE_MS = 5 * 60 * 1000;
let publisherCache = { expiresAt: 0, items: [] };
let publisherRequest = null;

function publisherUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function timeLabel(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Bangkok",
  }).format(date);
}

function getPublisherItems(forceRefresh = false) {
  if (!forceRefresh && publisherCache.expiresAt > Date.now()) return Promise.resolve(publisherCache.items);
  if (!publisherRequest) {
    publisherRequest = newsApi.today()
      .then((result) => {
        const items = (result.items || []).filter((item) => item.title && publisherUrl(item.url)).slice(0, 3);
        publisherCache = { expiresAt: Date.now() + PUBLISHER_CACHE_MS, items };
        return items;
      })
      .finally(() => { publisherRequest = null; });
  }
  return publisherRequest;
}

/** Small attributed publisher headlines to complement member posts during early growth. */
export default function PublisherHighlights() {
  const app = useApp();
  const [items, setItems] = useState(() => publisherCache.items);
  const [loading, setLoading] = useState(() => !publisherCache.items.length);
  const [error, setError] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      setItems(await getPublisherItems(true));
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    getPublisherItems().then((nextItems) => { if (active) setItems(nextItems); })
      .catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  if (!loading && !items.length && !error) return null;

  return (
    <section className="social-publisher-feed" aria-labelledby="social-publisher-feed-title">
      <header className="social-publisher-feed__heading">
        <div><span><Newspaper size={15} /> FROM PUBLISHERS</span><h3 id="social-publisher-feed-title">News & discovery</h3></div>
        <button type="button" onClick={() => app.setSection("today")} aria-label="Open Today news"><span>Today</span><ArrowRight size={15} /></button>
      </header>
      {loading ? <p className="social-publisher-feed__state" role="status">Loading publisher headlines…</p> : null}
      {error ? <p className="social-publisher-feed__state" role="status">Headlines are temporarily unavailable. <button type="button" onClick={refresh}><RefreshCw size={14} /> Retry</button></p> : null}
      {!loading && items.length ? <div className="social-publisher-feed__items">
        {items.map((item) => <article className="social-publisher-card" key={item.id || item.url}>
          {item.image_url ? <a className="social-publisher-card__image" href={publisherUrl(item.url)} target="_blank" rel="noopener noreferrer" aria-label={`Open ${item.title} at ${item.source}`}>
            <img src={item.image_url} alt="" loading="lazy" decoding="async" referrerPolicy="strict-origin-when-cross-origin" onError={(event) => { event.currentTarget.parentElement.hidden = true; }} />
          </a> : null}
          <div className="social-publisher-card__body">
            <div className="social-publisher-card__meta"><span>{item.source || "Publisher"}{item.category_label ? ` · ${item.category_label}` : ""}</span>{item.published_at ? <time dateTime={item.published_at}>{timeLabel(item.published_at)}</time> : null}</div>
            <h4><a href={publisherUrl(item.url)} target="_blank" rel="noopener noreferrer">{item.title}<ExternalLink size={13} aria-hidden="true" /></a></h4>
            {item.summary ? <p>{item.summary}</p> : null}
            <span className="social-publisher-card__attribution">Publisher content · Open original source</span>
          </div>
        </article>)}
      </div> : null}
    </section>
  );
}
