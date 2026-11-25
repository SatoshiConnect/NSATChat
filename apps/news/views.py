"""Read-only, cached daily headlines from fixed and attributed news sources."""

from datetime import datetime, timezone as datetime_timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import json
import re
from difflib import SequenceMatcher
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView


FEEDS = (
    {"url": "https://www.thailand.go.th/useful-rss?hl=th", "label": "Thailand.go.th", "category": "news", "category_label": "Thailand news"},
    {"url": "https://www.thailand.go.th/issue-rss?hl=th", "label": "Thailand.go.th", "category": "topics", "category_label": "Topics"},
    {"url": "https://www.thailand.go.th/event-rss?hl=th", "label": "Thailand.go.th", "category": "events", "category_label": "Events"},
    {"url": "https://www.nasa.gov/news-release/feed/", "label": "NASA", "category": "science", "category_label": "Science"},
)
FEED_LABEL = "Thailand.go.th · NASA · GDELT Project"
FRESH_CACHE_KEY = "today-news:thailand-prd:v5"
STALE_CACHE_KEY = "today-news:thailand-prd:stale:v5"
FRESH_TTL_SECONDS = 300
STALE_TTL_SECONDS = 86400
MAX_FEED_BYTES = 1_500_000
MAX_ITEMS = 60
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERY = '(Thailand OR earthquake OR election OR parliament OR government OR economy OR business OR health OR science OR technology OR climate OR war OR sports OR disaster OR education)'


def _today_bangkok():
    return timezone.now().astimezone(BANGKOK_TZ).date()


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain_text(value, limit):
    parser = _TextOnly()
    try:
        parser.feed(str(value or ""))
        text = " ".join(" ".join(parser.parts).split())
    except Exception:
        text = re.sub(r"<[^>]*>", " ", str(value or ""))
        text = " ".join(text.split())
    return text[:limit]


def _local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element, *names):
    wanted = set(names)
    for child in element:
        if _local_name(child.tag) in wanted:
            if _local_name(child.tag) == "link" and child.attrib.get("href"):
                return child.attrib["href"]
            return "".join(child.itertext()).strip()
    return ""


def _published_at(element):
    raw = _child_text(element, "pubdate", "published", "updated", "date")
    if not raw:
        return None
    try:
        value = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime_timezone.utc)
    return value.astimezone(datetime_timezone.utc)


def _safe_article_link(raw):
    # Never allow an RSS entry to turn into a javascript:, data:, or local URL.
    value = str(raw or "").strip()
    if value.startswith("https://") and len(value) <= 2048:
        return value
    return ""


def _fetch_feed(feed):
    request = Request(
        feed["url"],
        headers={"User-Agent": "SatoshiCoreToday/1.0 (+https://chat.satoshicore.org)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"},
    )
    with urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise URLError(f"Feed returned HTTP {response.status}")
        payload = response.read(MAX_FEED_BYTES + 1)
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("RSS feed exceeded the configured size limit")

    root = ET.fromstring(payload)
    entries = [node for node in root.iter() if _local_name(node.tag) in ("item", "entry")]
    today = _today_bangkok()
    items = []
    seen = set()
    for entry in entries:
        title = _plain_text(_child_text(entry, "title"), 240)
        link = _safe_article_link(_child_text(entry, "link", "guid"))
        published = _published_at(entry)
        if not title or not link or not published or published.astimezone(BANGKOK_TZ).date() != today:
            continue
        if link in seen:
            continue
        seen.add(link)
        summary = _plain_text(_child_text(entry, "description", "summary", "content"), 420)
        items.append({
            "id": link,
            "title": title,
            "summary": summary,
            "url": link,
            "source": feed["label"],
            "category": feed["category"],
            "category_label": feed["category_label"],
            "published_at": published.isoformat(),
        })
        if len(items) >= MAX_ITEMS:
            break
    items.sort(key=lambda item: item["published_at"], reverse=True)
    return items


def _fetch_global_news():
    """Fetch a small, rolling set of global headlines from GDELT's public DOC API."""
    params = urlencode({
        "query": GDELT_QUERY,
        "mode": "artlist",
        "format": "json",
        "maxrecords": 60,
        "timespan": "1d",
        "sort": "datedesc",
    })
    request = Request(
        f"{GDELT_API}?{params}",
        headers={"User-Agent": "SatoshiCoreToday/1.0 (+https://chat.satoshicore.org)", "Accept": "application/json"},
    )
    # GDELT is optional: do not make a user's Today page wait on a slow global source.
    with urlopen(request, timeout=3) as response:
        if response.status != 200:
            raise URLError(f"GDELT returned HTTP {response.status}")
        payload = response.read(MAX_FEED_BYTES + 1)
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("Global news response exceeded the configured size limit")
    result = json.loads(payload.decode("utf-8"))
    today = _today_bangkok()
    items = []
    for article in result.get("articles", []):
        title = _plain_text(article.get("title"), 240)
        link = _safe_article_link(article.get("url"))
        raw_date = str(article.get("seendate") or "")
        try:
            published = datetime.strptime(raw_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime_timezone.utc)
        except (TypeError, ValueError):
            continue
        if not title or not link or published.astimezone(BANGKOK_TZ).date() != today:
            continue
        country = str(article.get("sourcecountry") or "").strip().casefold()
        domain = _plain_text(article.get("domain"), 120) or "News publisher"
        items.append({
            "id": link,
            "title": title,
            "summary": "",
            "url": link,
            "source": domain,
            "category": "thailand" if country in {"th", "thailand"} else "world",
            "category_label": "Thailand" if country in {"th", "thailand"} else "World",
            "published_at": published.isoformat(),
        })
    return items


def _fetch_today_items():
    items = []
    failures = 0
    successful_sources = set()
    with ThreadPoolExecutor(max_workers=len(FEEDS) + 1) as executor:
        future_sources = {executor.submit(_fetch_feed, feed): feed["label"] for feed in FEEDS}
        future_sources[executor.submit(_fetch_global_news)] = "GDELT Project"
        for future in as_completed(future_sources):
            try:
                result = future.result()
                items.extend(result)
                successful_sources.add(future_sources[future])
            except Exception:
                failures += 1
    if failures == len(FEEDS) + 1:
        raise URLError("All configured Today news sources are unavailable")
    unique = {item["url"]: item for item in items}
    items = _rank_coverage(unique.values())[:MAX_ITEMS]
    today = _today_bangkok()
    source_label = " · ".join(sorted(successful_sources)) or FEED_LABEL
    return {
        "items": items,
        "source": source_label,
        "sources": sorted(successful_sources),
        "global_available": "GDELT Project" in successful_sources,
        "fetched_at": timezone.now().isoformat(),
        "date": today.isoformat(),
    }


def _rank_coverage(items):
    """Group near-identical headlines; rank by distinct publisher coverage, then recency."""
    clusters = []
    for item in sorted(items, key=lambda value: value["published_at"], reverse=True):
        normalized = re.sub(r"[^\w]", "", item.get("title", "").casefold())
        source = item.get("source") or "Unknown publisher"
        match = None
        for cluster in clusters:
            if SequenceMatcher(None, normalized, cluster["normalized"]).ratio() >= 0.9:
                match = cluster
                break
        if match is None:
            clusters.append({"normalized": normalized, "item": item, "sources": {source}})
        else:
            match["sources"].add(source)

    ranked = []
    for cluster in clusters:
        item = dict(cluster["item"])
        publisher_count = len(cluster["sources"])
        item["coverage_count"] = publisher_count
        item["interest_rating"] = min(5, publisher_count)
        ranked.append(item)
    return sorted(ranked, key=lambda item: (item["interest_rating"], item["published_at"]), reverse=True)


class TodayNewsFeedAPIView(APIView):
    """Serve today's cached headlines with local category and keyword filtering."""

    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "today_news"

    def get(self, request):
        cached = cache.get(FRESH_CACHE_KEY)
        if cached:
            return Response(self._filtered(request, cached, stale=False))
        try:
            fresh = _fetch_today_items()
        except Exception:
            stale = cache.get(STALE_CACHE_KEY)
            if stale:
                return Response(self._filtered(request, stale, stale=True))
            return Response(
                {"detail": "Today's news source is temporarily unavailable.", "items": [], "source": FEED_LABEL},
                status=503,
            )
        cache.set(FRESH_CACHE_KEY, fresh, FRESH_TTL_SECONDS)
        cache.set(STALE_CACHE_KEY, fresh, STALE_TTL_SECONDS)
        return Response(self._filtered(request, fresh, stale=False))

    @staticmethod
    def _filtered(request, feed, *, stale):
        category = (request.query_params.get("category") or "all").strip().lower()
        query = (request.query_params.get("q") or "").strip()[:100].casefold()
        allowed = {"all", "thailand", "world", *(source["category"] for source in FEEDS)}
        if category not in allowed:
            category = "all"
        items = feed.get("items", [])
        if category != "all":
            items = [item for item in items if item.get("category") == category]
        if query:
            items = [
                item for item in items
                if query in f"{item.get('title', '')} {item.get('summary', '')}".casefold()
            ]
        return {
            **feed,
            "items": items,
            "stale": stale,
            "categories": [
                {"id": "all", "label": "All"},
                {"id": "thailand", "label": "Thailand"},
                {"id": "world", "label": "World"},
                *[{"id": source["category"], "label": source["category_label"]} for source in FEEDS],
            ],
        }
