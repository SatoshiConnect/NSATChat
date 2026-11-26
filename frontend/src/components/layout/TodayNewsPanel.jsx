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
  const [showMore, setShowMore] = useState(false);

  const fetchFeed = useCallback(() => newsApi.today(), []);
  const globalNewsAvailable = feed?.global_available ?? String(feed?.source || "").includes("GDELT");
  const visibleItems = (feed?.items || []).filter((item) => {
    const matchesCategory = category === "all" || item.category === category || item.region === category;
    const needle = query.trim().toLocaleLowerCase();
    const matchesQuery = !needle || `${item.title} ${item.summary || ""}`.toLocaleLowerCase().includes(needle);
    return matchesCategory && matchesQuery;
  });
  const featuredItem = visibleItems.find((item) => item.image_url) || visibleItems[0];
  const remainingItems = featuredItem ? visibleItems.filter((item) => item.id !== featuredItem.id) : [];
  const storyItems = showMore ? remainingItems : remainingItems.slice(0, 12);

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
          <div><h2>Today’s briefing</h2><span>{feed?.date ? new Date(`${feed.date}T12:00:00Z`).toLocaleDateString(undefined, { timeZone: "Asia/Bangkok", weekday: "short", day: "numeric", month: "short" }) : "Today"}</span></div>
          {feed?.fetched_at ? <small>Updated {formatNewsTime(feed.fetched_at)} · {feed.sources?.length || 1} sources</small> : null}
        </div>
        <label className="today-news__search">
          <Search size={18} aria-hidden="true" />
          <input value={query} onChange={(event) => { setQuery(event.target.value); setShowMore(false); }} placeholder="Search today’s news" aria-label="Search today's news" />
          {query ? <button type="button" onClick={() => { setQuery(""); setShowMore(false); }} aria-label="Clear search">×</button> : null}
        </label>
        <div className="today-news__filters" role="group" aria-label="Filter news category">
          {(feed?.categories || [
            { id: "all", label: "All" }, { id: "thailand", label: "Thailand" }, { id: "world", label: "World" },
            { id: "business", label: "Business" }, { id: "technology", label: "Technology" }, { id: "science", label: "Science" },
            { id: "health", label: "Health" }, { id: "sports", label: "Sports" }, { id: "culture", label: "Culture" },
          ]).map((item) => (
            <button key={item.id} type="button" className={category === item.id ? "is-active" : ""} aria-pressed={category === item.id} onClick={() => { setCategory(item.id); setShowMore(false); }}>{item.label}</button>
          ))}
        </div>
        {feed?.stale ? <p className="today-news__notice">Showing the last saved update. It could not be refreshed just now.</p> : null}
        {feed && !globalNewsAvailable ? <p className="today-news__notice">Some international news sources are temporarily unavailable. Showing headlines from sources that responded.</p> : null}
        {loading && !feed ? <div className="today-news__state" role="status">Loading today’s news…</div> : null}
        {error ? <div className="today-news__state today-news__state--error" role="alert">{error}<button type="button" onClick={load}>Retry</button></div> : null}
        {!loading && !error && featuredItem ? (
          <>
            <article className="today-news__featured">
              <a className={`today-news__featured-media${featuredItem.image_url ? " has-image" : ""}`} href={featuredItem.url} target="_blank" rel="noopener noreferrer">
                <span className="today-news__image-fallback"><Newspaper size={30} /></span>
                {featuredItem.image_url ? <img src={featuredItem.image_url} alt="" fetchPriority="high" decoding="async" referrerPolicy="strict-origin-when-cross-origin" onError={(event) => { event.currentTarget.hidden = true; }} /> : null}
                <span className="today-news__featured-shade" />
                <span className="today-news__featured-tag">Top story · {featuredItem.category_label}</span>
                <span className="today-news__featured-copy">
                  <span>{featuredItem.source} · {formatNewsTime(featuredItem.published_at)}</span>
                  <strong>{featuredItem.title}</strong>
                  <span className="today-news__featured-link">Read story <ArrowUpRight size={15} /></span>
                </span>
              </a>
              {featuredItem.summary ? <p className="today-news__featured-summary">{featuredItem.summary}</p> : null}
            </article>
            <div className="today-news__section-heading">
              <div><h3>More stories</h3><span>{visibleItems.length} updates</span></div>
              {Number.isFinite(Number(featuredItem.interest_rating)) ? <span className="today-news__rating" title="Based on the number of distinct publishers reporting similar headlines; this is not a fact-check."><TrendingUp size={13} /> Coverage {featuredItem.interest_rating}/5</span> : null}
            </div>
            <div className="today-news__stories">
              {storyItems.map((item) => (
                <article className="today-news__story" key={item.id}>
                  <a className={`today-news__story-image${item.image_url ? " has-image" : ""}`} href={item.url} target="_blank" rel="noopener noreferrer" aria-label={`Read: ${item.title}`}>
                    <span className="today-news__image-fallback"><Newspaper size={20} /></span>
                    {item.image_url ? <img src={item.image_url} alt="" loading="lazy" decoding="async" referrerPolicy="strict-origin-when-cross-origin" onError={(event) => { event.currentTarget.hidden = true; }} /> : null}
                  </a>
                  <div className="today-news__story-body">
                    <div className="today-news__story-meta">
                      <span>{item.category_label}{item.region && item.region !== item.category ? ` · ${item.region_label}` : ""} · {item.source}</span>
                      <time dateTime={item.published_at}>{formatNewsTime(item.published_at)}</time>
                    </div>
                    <h4><a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}<ExternalLink size={13} /></a></h4>
                    {item.summary ? <p>{item.summary}</p> : null}
                    {Number.isFinite(Number(item.interest_rating)) ? <span className="today-news__rating-mini"><TrendingUp size={12} /> {item.coverage_count || 1} sources</span> : null}
                  </div>
                </article>
              ))}
            </div>
            {!showMore && remainingItems.length > storyItems.length ? (
              <button className="today-news__more" type="button" onClick={() => setShowMore(true)}>Show {remainingItems.length - storyItems.length} more stories</button>
            ) : null}
          </>
        ) : null}
        {!loading && !error && !visibleItems.length ? (
          <div className="today-news__state">
            <span className="today-news__icon"><Newspaper size={26} /></span>
            <strong>{query || category !== "all" ? "No matching headlines" : "No stories published today"}</strong>
            <p>{query || category !== "all" ? "Try another search or category." : "Today refreshes from Thai and international publishers. Social posts and Stories are shown in Social."}</p>
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
