"""Read-only, cached news headlines from a fixed, attributed RSS source."""

from datetime import datetime, timezone as datetime_timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import re
from urllib.error import URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from django.core.cache import cache
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView


FEEDS = (
    {"url": "https://www.thailand.go.th/useful-rss?hl=th", "label": "Thailand.go.th · News"},
    {"url": "https://www.thailand.go.th/issue-rss?hl=th", "label": "Thailand.go.th · Topics"},
    {"url": "https://www.thailand.go.th/event-rss?hl=th", "label": "Thailand.go.th · Events"},
)
FEED_LABEL = "Thailand.go.th · Government Public Relations Department"
FRESH_CACHE_KEY = "today-news:thailand-prd:v2"
STALE_CACHE_KEY = "today-news:thailand-prd:stale:v2"
FRESH_TTL_SECONDS = 300
STALE_TTL_SECONDS = 86400
MAX_FEED_BYTES = 1_500_000
MAX_ITEMS = 60


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
    today = timezone.localdate()
    items = []
    seen = set()
    for entry in entries:
        title = _plain_text(_child_text(entry, "title"), 240)
        link = _safe_article_link(_child_text(entry, "link", "guid"))
        published = _published_at(entry)
        if not title or not link or not published or timezone.localtime(published).date() != today:
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
            "published_at": published.isoformat(),
        })
        if len(items) >= MAX_ITEMS:
            break
    items.sort(key=lambda item: item["published_at"], reverse=True)
    return items


def _fetch_today_items():
    items = []
    failures = 0
    with ThreadPoolExecutor(max_workers=len(FEEDS)) as executor:
        futures = [executor.submit(_fetch_feed, feed) for feed in FEEDS]
        for future in as_completed(futures):
            try:
                items.extend(future.result())
            except Exception:
                failures += 1
    if failures == len(FEEDS):
        raise URLError("All configured Today news feeds are unavailable")
    unique = {item["url"]: item for item in items}
    items = sorted(unique.values(), key=lambda item: item["published_at"], reverse=True)[:MAX_ITEMS]
    today = timezone.localdate()
    return {"items": items, "source": FEED_LABEL, "fetched_at": timezone.now().isoformat(), "date": today.isoformat()}


class TodayNewsFeedAPIView(APIView):
    """Serve today's headlines, refreshing from the allowlisted RSS source every five minutes."""

    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "today_news"

    def get(self, request):
        cached = cache.get(FRESH_CACHE_KEY)
        if cached:
            return Response({**cached, "stale": False})
        try:
            fresh = _fetch_today_items()
        except Exception:
            stale = cache.get(STALE_CACHE_KEY)
            if stale:
                return Response({**stale, "stale": True})
            return Response(
                {"detail": "Today's news source is temporarily unavailable.", "items": [], "source": FEED_LABEL},
                status=503,
            )
        cache.set(FRESH_CACHE_KEY, fresh, FRESH_TTL_SECONDS)
        cache.set(STALE_CACHE_KEY, fresh, STALE_TTL_SECONDS)
        return Response({**fresh, "stale": False})
