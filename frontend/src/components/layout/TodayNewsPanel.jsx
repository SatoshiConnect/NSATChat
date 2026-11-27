import { ArrowRight, BookOpen, BriefcaseBusiness, Cpu, FlaskConical, Globe, HeartPulse, MapPin, Newspaper, Palette, Play, RefreshCw, Search, TrendingUp, Trophy, Video, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { newsApi } from "../../api/endpoints";
import { useApp } from "./AppContext";

const CATEGORY_ICONS = {
  all: Newspaper,
  thailand: MapPin,
  world: Globe,
  business: BriefcaseBusiness,
  technology: Cpu,
  science: FlaskConical,
  health: HeartPulse,
  sports: Trophy,
  culture: Palette,
};

const formatNewsTime = (value) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bangkok" }).format(date);
};

const hasVideo = (item) => item?.video_provider === "youtube" && /^[A-Za-z0-9_-]{11}$/.test(String(item.video_id || ""));

const formatNewsDateTime = (value) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bangkok" }).format(date);
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
  const [activeStory, setActiveStory] = useState(null);
  const closeReaderRef = useRef(null);
  const returnFocusRef = useRef(null);

  const fetchFeed = useCallback(() => newsApi.today(), []);
  const globalNewsAvailable = feed?.global_available ?? String(feed?.source || "").includes("GDELT");
  const visibleItems = (feed?.items || []).filter((item) => {
    const matchesCategory = category === "all" || item.category === category || item.region === category;
    const needle = query.trim().toLocaleLowerCase();
    const matchesQuery = !needle || `${item.title} ${item.summary || ""}`.toLocaleLowerCase().includes(needle);
    return matchesCategory && matchesQuery;
  });
  const featuredItem = visibleItems.find((item) => item.image_url) || visibleItems[0];
  const visualCandidates = visibleItems.filter((item) => item.id !== featuredItem?.id && (item.image_url || hasVideo(item)));
  const diverseVisualItems = visualCandidates.filter((item, index, all) => all.findIndex((candidate) => candidate.category === item.category) === index);
  const visualItems = [...diverseVisualItems, ...visualCandidates]
    .filter((item, index, all) => all.findIndex((candidate) => candidate.id === item.id) === index)
    .slice(0, 4);
  const visualItemIds = new Set(visualItems.map((item) => item.id));
  const remainingItems = featuredItem ? visibleItems.filter((item) => item.id !== featuredItem.id && !visualItemIds.has(item.id)) : [];
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

  useEffect(() => {
    if (!activeStory) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeReaderRef.current?.focus();

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        setActiveStory(null);
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = document.querySelector(".today-news__reader-dialog");
      const focusable = dialog?.querySelectorAll('button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])');
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
      returnFocusRef.current?.focus?.();
      returnFocusRef.current = null;
    };
  }, [activeStory]);

  const openStory = (item, event) => {
    returnFocusRef.current = event.currentTarget;
    setActiveStory(item);
  };

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
          ]).map((item) => {
            const Icon = CATEGORY_ICONS[item.id] || Newspaper;
            return (
              <button key={item.id} type="button" className={category === item.id ? "is-active" : ""} aria-pressed={category === item.id} onClick={() => { setCategory(item.id); setShowMore(false); }}>
                <Icon size={15} aria-hidden="true" />
                {item.label}
              </button>
            );
          })}
        </div>
        {feed?.stale ? <p className="today-news__notice">Showing the last saved update. It could not be refreshed just now.</p> : null}
        {feed && !globalNewsAvailable ? <p className="today-news__notice">Some international news sources are temporarily unavailable. Showing headlines from sources that responded.</p> : null}
        {loading && !feed ? <div className="today-news__state" role="status">Loading today’s news…</div> : null}
        {error ? <div className="today-news__state today-news__state--error" role="alert">{error}<button type="button" onClick={load}>Retry</button></div> : null}
        {!loading && !error && visualItems.length >= 2 ? (
          <section className="today-news__visuals" aria-label="Photo and video stories">
            <div className="today-news__visuals-heading"><div><span>IN FOCUS</span><h3>Stories in pictures &amp; video</h3></div><small>{visualItems.filter(hasVideo).length} videos · {visualItems.length} stories</small></div>
            <div className="today-news__visuals-rail">
              {visualItems.map((item) => (
                <article className="today-news__visual-card" key={item.id}>
                  <button type="button" className="today-news__visual-media" onClick={(event) => openStory(item, event)} aria-label={`${hasVideo(item) ? "Watch video in app" : "Read story in app"}: ${item.title}`}>
                    <span className="today-news__image-fallback"><Newspaper size={24} /></span>
                    <img src={item.image_url} alt="" loading="lazy" decoding="async" referrerPolicy="strict-origin-when-cross-origin" onError={(event) => { event.currentTarget.hidden = true; }} />
                    <span className="today-news__visual-shade" />
                    {hasVideo(item) ? <span className="today-news__visual-play" aria-hidden="true"><Play size={22} fill="currentColor" /></span> : null}
                    <span className="today-news__visual-category">{hasVideo(item) ? <><Video size={12} /> VIDEO · </> : null}{item.category_label}</span>
                    <strong>{item.title}</strong>
                  </button>
                  <div className="today-news__visual-meta"><span>{item.source}</span><time dateTime={item.published_at}>{formatNewsTime(item.published_at)}</time></div>
                </article>
              ))}
            </div>
          </section>
        ) : null}
        {!loading && !error && featuredItem ? (
          <>
            <article className="today-news__featured">
              <button type="button" className={`today-news__featured-media${featuredItem.image_url ? " has-image" : ""}`} onClick={(event) => openStory(featuredItem, event)} aria-label={`${hasVideo(featuredItem) ? "Watch video in app" : "Read story in app"}: ${featuredItem.title}`}>
                <span className="today-news__image-fallback"><Newspaper size={30} /></span>
                {featuredItem.image_url ? <img src={featuredItem.image_url} alt="" fetchPriority="high" decoding="async" referrerPolicy="strict-origin-when-cross-origin" onError={(event) => { event.currentTarget.hidden = true; }} /> : null}
                <span className="today-news__featured-shade" />
                <span className="today-news__featured-tag">{hasVideo(featuredItem) ? "VIDEO · " : "Top story · "}{featuredItem.category_label}</span>
                {hasVideo(featuredItem) ? <span className="today-news__featured-play" aria-hidden="true"><Play size={26} fill="currentColor" /></span> : null}
                <span className="today-news__featured-copy">
                  <span>{featuredItem.source} · {formatNewsTime(featuredItem.published_at)}</span>
                  <strong>{featuredItem.title}</strong>
                  <span className="today-news__featured-link">Read in app <BookOpen size={15} /></span>
                </span>
              </button>
              {featuredItem.summary ? <p className="today-news__featured-summary">{featuredItem.summary}</p> : null}
              <button type="button" className="today-news__read-inline" onClick={(event) => openStory(featuredItem, event)}>Read summary <ArrowRight size={15} /></button>
            </article>
            <div className="today-news__section-heading">
              <div><h3>More stories</h3><span>{remainingItems.length} stories</span></div>
              {Number.isFinite(Number(featuredItem.interest_rating)) ? <span className="today-news__rating" title="Based on the number of distinct publishers reporting similar headlines; this is not a fact-check."><TrendingUp size={13} /> Coverage {featuredItem.interest_rating}/5</span> : null}
            </div>
            <div className="today-news__stories">
              {storyItems.map((item) => (
                <article className="today-news__story" key={item.id}>
                  <button type="button" className={`today-news__story-image${item.image_url ? " has-image" : ""}`} onClick={(event) => openStory(item, event)} aria-label={`Read summary in app: ${item.title}`}>
                    <span className="today-news__image-fallback"><Newspaper size={20} /></span>
                    {item.image_url ? <img src={item.image_url} alt="" loading="lazy" decoding="async" referrerPolicy="strict-origin-when-cross-origin" onError={(event) => { event.currentTarget.hidden = true; }} /> : null}
                  </button>
                  <div className="today-news__story-body">
                    <div className="today-news__story-meta">
                      <span>{item.category_label}{item.region && item.region !== item.category ? ` · ${item.region_label}` : ""} · {item.source}</span>
                      <time dateTime={item.published_at}>{formatNewsTime(item.published_at)}</time>
                    </div>
                    <h4><button type="button" onClick={(event) => openStory(item, event)}>{item.title}</button></h4>
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
        <span>Coverage rating reflects distinct publishers, not fact-checking. Stories open here in Today.</span>
        <button type="button" onClick={() => app.setSection("status")}>Go to Social <ArrowRight size={15} /></button>
      </footer>
      {activeStory ? createPortal(
        <div className="today-news__reader-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setActiveStory(null); }}>
          <section className="today-news__reader-dialog" role="dialog" aria-modal="true" aria-labelledby="today-news-reader-title" tabIndex={-1}>
            <header className="today-news__reader-header">
              <div><span><BookOpen size={16} /> Today reader</span><small>{activeStory.category_label}{activeStory.region && activeStory.region !== activeStory.category ? ` · ${activeStory.region_label}` : ""}</small></div>
              <button ref={closeReaderRef} type="button" onClick={() => setActiveStory(null)} aria-label="Close news reader"><X size={21} /></button>
            </header>
            <div className="today-news__reader-scroll">
              {hasVideo(activeStory) ? (
                <div className="today-news__reader-video"><iframe src={`https://www.youtube-nocookie.com/embed/${activeStory.video_id}?playsinline=1&rel=0`} title={activeStory.title} loading="lazy" allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerPolicy="strict-origin-when-cross-origin" allowFullScreen /></div>
              ) : activeStory.image_url ? <img className="today-news__reader-image" src={activeStory.image_url} alt="" decoding="async" referrerPolicy="strict-origin-when-cross-origin" onError={(event) => { event.currentTarget.hidden = true; }} /> : null}
              <div className="today-news__reader-body">
                <div className="today-news__reader-byline"><span>{activeStory.source}</span><time dateTime={activeStory.published_at}>{formatNewsDateTime(activeStory.published_at)}</time></div>
                <h2 id="today-news-reader-title">{activeStory.title}</h2>
                <div className="today-news__reader-section"><span>News summary</span><p>{activeStory.summary || "A summary is not available from this publisher’s feed."}</p></div>
                <p className="today-news__reader-note">This in-app reader shows the headline and summary supplied by the news feed. It will not open an external website.</p>
              </div>
            </div>
          </section>
        </div>,
        document.body,
      ) : null}
    </section>
  );
}
