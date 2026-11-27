import { ExternalLink, Newspaper, Play } from "lucide-react";
import { useState } from "react";
import { detailTime } from "../../utils/format";

function secureUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function publisherVideo(item) {
  const videoUrl = secureUrl(item.video_url);
  return videoUrl ? videoUrl : "";
}

function youtubeVideoId(value) {
  const secure = secureUrl(value);
  if (!secure) return "";
  const url = new URL(secure);
  const host = url.hostname.toLowerCase();
  if (host === "youtu.be") return url.pathname.split("/").filter(Boolean)[0] || "";
  if (host !== "youtube.com" && host !== "www.youtube.com") return "";
  return url.searchParams.get("v") || url.pathname.match(/^\/(?:embed|shorts|live)\/([\w-]{11})(?:\/|$)/)?.[1] || "";
}

function youtubeThumbnail(videoId) {
  return videoId ? `https://i.ytimg.com/vi/${encodeURIComponent(videoId)}/hqdefault.jpg` : "";
}

export default function PublisherSystemPost({ item }) {
  const [playEmbeddedVideo, setPlayEmbeddedVideo] = useState(false);
  const sourceUrl = secureUrl(item.url);
  const videoUrl = publisherVideo(item);
  const youtubeId = youtubeVideoId(videoUrl);
  const imageUrl = secureUrl(item.image_url) || youtubeThumbnail(youtubeId);
  return (
    <article className="social-post social-post--publisher">
      <header className="social-post__author">
        <span className="social-system-avatar" aria-hidden="true"><Newspaper size={21} /></span>
        <div className="social-system-post__identity">
          <strong>NSAT Social · News</strong>
          <span>System post · {item.source || "Publisher"}{item.published_at ? ` · ${detailTime(item.published_at)}` : ""}</span>
        </div>
        <span className="social-system-post__badge">SYSTEM</span>
      </header>
      {youtubeId ? playEmbeddedVideo ? <iframe className="social-system-post__media social-system-post__video-frame" src={`https://www.youtube-nocookie.com/embed/${youtubeId}?autoplay=1&playsinline=1`} title={`Play ${item.title}`} allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture; web-share" referrerPolicy="strict-origin-when-cross-origin" allowFullScreen /> : <button type="button" className="social-system-post__video-preview" onClick={() => setPlayEmbeddedVideo(true)} aria-label={`Play video: ${item.title}`}>
        {imageUrl ? <img className="social-system-post__media" src={imageUrl} alt="" loading="lazy" decoding="async" referrerPolicy="strict-origin-when-cross-origin" /> : <span className="social-system-post__video-placeholder"><Newspaper size={28} /></span>}
        <span className="social-system-post__video-play"><Play size={20} fill="currentColor" /> Play</span>
      </button> : videoUrl ? <video className="social-post__image social-post__image--video social-system-post__media" controls playsInline preload="none" poster={imageUrl || undefined}>
        <source src={videoUrl} />
        Your browser cannot play this video. Open the source to watch it.
      </video> : imageUrl ? <a className="social-system-post__media-link" href={sourceUrl} target="_blank" rel="noopener noreferrer" aria-label={`Open ${item.title} from ${item.source || "publisher"}`}>
        <img className="social-post__image social-system-post__media" src={imageUrl} alt="" loading="lazy" decoding="async" referrerPolicy="strict-origin-when-cross-origin" onError={(event) => { event.currentTarget.hidden = true; }} />
        <span><ExternalLink size={15} /> Open at publisher</span>
      </a> : null}
      <p className="social-system-post__category">{item.category_label || item.region_label || "News & discovery"}</p>
      <h3 className="social-system-post__title">{item.title}</h3>
      <footer className="social-system-post__footer">
        <span>{Number(item.coverage_count) > 1 ? `Covered by ${item.coverage_count} publishers` : "Latest publisher update"}</span>
        <a href={sourceUrl} target="_blank" rel="noopener noreferrer">{youtubeId || videoUrl ? "Watch video" : "Read story"} <ExternalLink size={14} /></a>
      </footer>
    </article>
  );
}
