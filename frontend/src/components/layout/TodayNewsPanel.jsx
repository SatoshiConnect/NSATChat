import { ArrowUpRight, ExternalLink, Newspaper, RefreshCw, Search, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { newsApi } from "../../api/endpoints";
import { useApp } from "./AppContext";

const formatNewsTime = (value) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bangkok" }).format(date);
};

/** Editorial/news destination. Member posts and Stories live in Social. */
export default function TodayNewsPanel() {
  const app = useApp();
  const [feed, setFeed] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");

  const fetchFeed = useCallback(() => newsApi.today(), []);
  const globalNewsAvailable = feed?.global_available ?? String(feed?.source || "").includes("GDELT");
  const visibleItems = (feed?.items || []).filter((item) => {
    const matchesCategory = category === "all" || item.category === category;
    const needle = query.trim().toLocaleLowerCase();
    const matchesQuery = !needle || `${item.title} ${item.summary || ""}`.toLocaleLowerCase().includes(needle);
    return matchesCategory && matchesQuery;
  });

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
    const refresh = () => fetchFeed()
      .then((result) => { if (active) setFeed(result); })
      .catch(() => { if (active) setError("Today’s news could not be reached. Check your connection and try again."); })
      .finally(() => { if (active) setLoading(false); });
    refresh();
    const interval = window.setInterval(refresh, 5 * 60 * 1000);
    return () => { active = false; window.clearInterval(interval); };
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
          <div><h2>What’s happening today</h2><span>{feed?.date ? new Date(`${feed.date}T12:00:00Z`).toLocaleDateString(undefined, { timeZone: "Asia/Bangkok" }) : "Today"}</span></div>
          {feed?.fetched_at ? <small>Updated {formatNewsTime(feed.fetched_at)} · {feed.source}</small> : null}
        </div>
        <label className="today-news__search">
          <Search size={18} aria-hidden="true" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search today’s headlines" aria-label="Search today's headlines" />
          {query ? <button type="button" onClick={() => setQuery("")} aria-label="Clear search">×</button> : null}
        </label>
        <div className="today-news__filters" role="group" aria-label="Filter news category">
          {(feed?.categories || [{ id: "all", label: "All" }, { id: "thailand", label: "Thailand" }, { id: "world", label: "World" }, { id: "science", label: "Science" }, { id: "news", label: "Thailand news" }, { id: "topics", label: "Topics" }, { id: "events", label: "Events" }]).map((item) => (
            <button key={item.id} type="button" className={category === item.id ? "is-active" : ""} aria-pressed={category === item.id} onClick={() => setCategory(item.id)}>{item.label}</button>
          ))}
        </div>
        {feed?.stale ? <p className="today-news__notice">Showing the last saved update. It could not be refreshed just now.</p> : null}
        {feed && !globalNewsAvailable ? <p className="today-news__notice">Global headlines are not reaching the server right now. Showing today’s available Thailand news.</p> : null}
        {loading && !feed ? <div className="today-news__state" role="status">Loading today’s news…</div> : null}
        {error ? <div className="today-news__state today-news__state--error" role="alert">{error}<button type="button" onClick={load}>Retry</button></div> : null}
        {!loading && !error && visibleItems.length ? (
          <div className="today-news__stories">
            {visibleItems.map((item) => (
              <article className="today-news__story" key={item.id}>
                <div className="today-news__story-meta">
                  <span>{item.category_label} · {item.source}</span>
                  <time dateTime={item.published_at}>{formatNewsTime(item.published_at)}</time>
                </div>
                {Number.isFinite(Number(item.interest_rating)) ? (
                  <div className="today-news__rating" title="Coverage rating is based on the number of distinct publishers reporting similar headlines. It is not a fact-check or quality score.">
                    <TrendingUp size={14} /> Coverage {item.interest_rating}/5 · {item.coverage_count || 1} {Number(item.coverage_count) === 1 ? "publisher" : "publishers"}
                  </div>
                ) : null}
                <h3><a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}<ExternalLink size={14} /></a></h3>
                {item.summary ? <p>{item.summary}</p> : null}
                <a className="today-news__read" href={item.url} target="_blank" rel="noopener noreferrer">Read at source <ArrowUpRight size={15} /></a>
              </article>
            ))}
          </div>
        ) : null}
        {!loading && !error && !visibleItems.length ? (
          <div className="today-news__state">
            <span className="today-news__icon"><Newspaper size={26} /></span>
            <strong>{query || category !== "all" ? "No matching headlines" : "No stories published today"}</strong>
            <p>{query || category !== "all" ? "Try another search or category." : "Today refreshes from Thailand.go.th and GDELT global news. Social posts and Stories are shown in Social."}</p>
          </div>
        ) : null}
      </div>

      <footer className="today-news__footer">
        <span>Coverage rating reflects distinct publishers, not fact-checking. Headlines link to publishers. Global coverage: <a href="https://www.gdeltproject.org/" target="_blank" rel="noopener noreferrer">GDELT Project</a>.</span>
        <button type="button" onClick={() => app.setSection("status")}>Go to Social <ArrowUpRight size={15} /></button>
      </footer>
    </section>
  );
}
