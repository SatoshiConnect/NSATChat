import { ArrowUpRight, ExternalLink, Newspaper, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { newsApi } from "../../api/endpoints";
import { useApp } from "./AppContext";

const formatNewsTime = (value) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(date);
};

/** Editorial/news destination. Member posts and Stories live in Social. */
export default function TodayNewsPanel() {
  const app = useApp();
  const [feed, setFeed] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchFeed = useCallback(() => newsApi.today(), []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setFeed(await fetchFeed());
    } catch {
      setError("Today’s news could not be reached. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  }, [fetchFeed]);

  useEffect(() => {
    let active = true;
    fetchFeed()
      .then((result) => { if (active) setFeed(result); })
      .catch(() => { if (active) setError("Today’s news could not be reached. Check your connection and try again."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [fetchFeed]);

  return (
    <section className="today-news panel" aria-labelledby="today-news-title">
      <header className="today-news__header">
        <div>
          <span className="today-news__eyebrow"><Newspaper size={15} /> NEWS</span>
          <h1 id="today-news-title">Today</h1>
          <p>Latest news and what is happening today.</p>
        </div>
        <button type="button" className="today-news__refresh" onClick={load} disabled={loading} aria-label="Refresh today’s news">
          <RefreshCw size={19} className={loading ? "is-spinning" : ""} />
        </button>
      </header>

      <div className="today-news__feed">
        <div className="today-news__feed-heading">
          <div><h2>Latest</h2><span>{feed?.date ? new Date(`${feed.date}T00:00:00`).toLocaleDateString() : "Today"}</span></div>
          {feed?.source ? <small>Source: {feed.source}</small> : null}
        </div>
        {feed?.stale ? <p className="today-news__notice">Showing the last saved update. It could not be refreshed just now.</p> : null}
        {loading && !feed ? <div className="today-news__state" role="status">Loading today’s news…</div> : null}
        {error ? <div className="today-news__state today-news__state--error" role="alert">{error}<button type="button" onClick={load}>Retry</button></div> : null}
        {!loading && !error && feed?.items?.length ? (
          <div className="today-news__stories">
            {feed.items.map((item) => (
              <article className="today-news__story" key={item.id}>
                <div className="today-news__story-meta"><span>{item.source}</span><time dateTime={item.published_at}>{formatNewsTime(item.published_at)}</time></div>
                <h3><a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}<ExternalLink size={14} /></a></h3>
                {item.summary ? <p>{item.summary}</p> : null}
                <a className="today-news__read" href={item.url} target="_blank" rel="noopener noreferrer">Read at source <ArrowUpRight size={15} /></a>
              </article>
            ))}
          </div>
        ) : null}
        {!loading && !error && !feed?.items?.length ? (
          <div className="today-news__state">
            <span className="today-news__icon"><Newspaper size={26} /></span>
            <strong>No stories published today in this feed</strong>
            <p>The news list updates automatically from Thailand.go.th’s public news, topics and events RSS feeds. Social posts and Stories are shown in Social.</p>
          </div>
        ) : null}
      </div>

      <footer className="today-news__footer">
        <span>News headlines are attributed to their publisher.</span>
        <button type="button" onClick={() => app.setSection("status")}>Go to Social <ArrowUpRight size={15} /></button>
      </footer>
    </section>
  );
}
