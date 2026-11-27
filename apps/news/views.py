"""Read-only, cached daily headlines from fixed and attributed news sources."""

from datetime import datetime, timedelta, timezone as datetime_timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import json
import re
from difflib import SequenceMatcher
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlsplit
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView


FEEDS = (
    {"url": "https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th", "label": "Google News Thailand", "category": "thailand", "category_label": "Thailand", "region": "thailand", "summary": False, "classify": True},
    {"url": "https://www.thailand.go.th/useful-rss?hl=th", "label": "Thailand.go.th", "category": "thailand", "category_label": "Thailand", "region": "thailand"},
    {"url": "https://www.thailand.go.th/issue-rss?hl=th", "label": "Thailand.go.th", "category": "thailand", "category_label": "Thailand", "region": "thailand"},
    {"url": "https://www.thailand.go.th/event-rss?hl=th", "label": "Thailand.go.th", "category": "thailand", "category_label": "Thailand", "region": "thailand"},
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml", "label": "BBC News", "category": "world", "category_label": "World", "region": "world", "global_source": True},
    {"url": "https://feeds.bbci.co.uk/news/world/asia/rss.xml", "label": "BBC News Asia", "category": "world", "category_label": "World", "region": "world", "global_source": True},
    {"url": "https://www.theguardian.com/world/rss", "label": "The Guardian", "category": "world", "category_label": "World", "region": "world", "global_source": True},
    {"url": "https://feeds.npr.org/1001/rss.xml", "label": "NPR", "category": "world", "category_label": "World", "region": "world", "global_source": True},
    {"url": "https://feeds.bbci.co.uk/news/business/rss.xml", "label": "BBC News Business", "category": "business", "category_label": "Business", "region": "world", "global_source": True},
    {"url": "https://feeds.bbci.co.uk/news/technology/rss.xml", "label": "BBC News Technology", "category": "technology", "category_label": "Technology", "region": "world", "global_source": True},
    {"url": "https://techcrunch.com/feed/", "label": "TechCrunch", "category": "technology", "category_label": "Technology", "region": "world", "global_source": True},
    {"url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "label": "BBC News Science & Environment", "category": "science", "category_label": "Science", "region": "world", "global_source": True},
    {"url": "https://www.nasa.gov/news-release/feed/", "label": "NASA", "category": "science", "category_label": "Science", "region": "world", "global_source": True},
    {"url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC16niRr50-MSBwiO3YDb3RA", "label": "BBC News Video", "category": "world", "category_label": "World video", "region": "world", "global_source": True, "media_type": "VIDEO"},
    {"url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCLA_DiR1FfKNvjuUpBHmylQ", "label": "NASA Video", "category": "science", "category_label": "Science video", "region": "world", "global_source": True, "media_type": "VIDEO"},
    {"url": "https://feeds.bbci.co.uk/news/health/rss.xml", "label": "BBC News Health", "category": "health", "category_label": "Health", "region": "world", "global_source": True},
    {"url": "https://www.who.int/rss-feeds/news-english.xml", "label": "World Health Organization", "category": "health", "category_label": "Health", "region": "world", "global_source": True},
    {"url": "https://feeds.bbci.co.uk/sport/rss.xml", "label": "BBC Sport", "category": "sports", "category_label": "Sports", "region": "world", "global_source": True},
    {"url": "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml", "label": "BBC News Culture", "category": "culture", "category_label": "Culture", "region": "world", "global_source": True},
)
FEED_LABEL = "BBC · Google News Thailand · The Guardian · NPR · NASA · YouTube · more"
FRESH_CACHE_KEY = "today-news:thailand-prd:v9"
STALE_CACHE_KEY = "today-news:thailand-prd:stale:v9"
FRESH_TTL_SECONDS = 300
STALE_TTL_SECONDS = 86400
MAX_FEED_BYTES = 1_500_000
MAX_ITEMS = 80
MAX_ITEMS_PER_FEED = 30
MAX_ITEMS_PER_CATEGORY = 12
FETCH_TIMEOUT_SECONDS = 3
IMAGE_HOSTS = (
    "ichef.bbci.co.uk",
    "i.guim.co.uk",
    "nasa.gov",
    "who.int",
    "techcrunch.com",
    "npr.org",
    "i.ytimg.com",
    "thailand.go.th",
)
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
CATEGORY_LABELS = {
    "thailand": "Thailand",
    "world": "World",
    "business": "Business",
    "technology": "Technology",
    "science": "Science",
    "health": "Health",
    "sports": "Sports",
    "culture": "Culture",
}
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


def _safe_image_link(raw, content_type=""):
    """Allow only HTTPS raster images from the configured editorial publishers."""
    value = str(raw or "").strip()
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        is_known_publisher = any(host == root or host.endswith(f".{root}") for root in IMAGE_HOSTS)
        if parsed.scheme != "https" or not is_known_publisher or parsed.username or parsed.password:
            return ""
        if parsed.port not in (None, 443):
            return ""
        if content_type and not content_type.lower().startswith("image/"):
            return ""
        if not re.search(r"\.(?:jpe?g|png|webp|avif)(?:$|[?#])", value, re.IGNORECASE):
            return ""
        return value[:2048]
    except (TypeError, ValueError):
        return ""


def _entry_image(entry):
    candidates = []
    for node in entry.iter():
        tag = _local_name(node.tag)
        if tag not in {"thumbnail", "content", "enclosure", "image"}:
            continue
        raw = node.attrib.get("url") or node.attrib.get("href")
        if not raw and tag == "image":
            raw = "".join(node.itertext()).strip()
        content_type = node.attrib.get("type", "")
        image_url = _safe_image_link(raw, content_type)
        if not image_url:
            continue
        try:
            width = int(node.attrib.get("width", "0"))
        except (TypeError, ValueError):
            width = 0
        candidates.append((width, tag != "thumbnail", image_url))
    return max(candidates, default=(0, False, ""))[2]


def _entry_video(entry):
    """Return a direct HTTPS video enclosure supplied by a configured publisher RSS feed."""
    for node in entry.iter():
        if _local_name(node.tag) not in {"content", "enclosure"}:
            continue
        content_type = node.attrib.get("type", "").lower()
        raw = node.attrib.get("url") or node.attrib.get("href")
        if content_type.startswith("video/") and _safe_article_link(raw):
            return raw[:2048]
    return ""


def _classify_headline(title, fallback):
    """Assign broad topics to aggregator headlines without rewriting their content."""
    text = str(title or "").casefold()
    topic_patterns = (
        ("sports", r"กีฬา|ฟุตบอล|ฟุตซอล|วอลเลย์บอล|บาสเกตบอล|นักกีฬา|ทีมชาติ|แชมป์|พรีเมียร์.?ลีก|เอฟเอคัพ|โอลิมปิก|\bsport(?:s)?\b|\bfootball\b|\bsoccer\b|\btennis\b|\bnba\b|\bfifa\b"),
        ("business", r"เศรษฐกิจ|ธุรกิจ|ตลาดหุ้น|หุ้น|ราคาทอง|ทองคำ|ค่าเงินบาท|ธนาคาร|บริษัท|ลงทุน|ส่งออก|การค้า|น้ำมัน|\bbusiness\b|\beconomy\b|\bmarket\b|\bstocks?\b|\bfinance\b|\btrade\b"),
        ("technology", r"เทคโนโลยี|ปัญญาประดิษฐ์|ไซเบอร์|แฮก|แฮ็ก|ดิจิทัล|สมาร์ตโฟน|มือถือ|แอปพลิเคชัน|\btechnology\b|\btech\b|\bai\b|\bcyber\b|\bsoftware\b|\bsmartphone\b|\bstartup\b"),
        ("health", r"สุขภาพ|สาธารณสุข|โรงพยาบาล|แพทย์|หมอ|ผู้ป่วย|โรคระบาด|วัคซีน|ยาใหม่|\bhealth\b|\bmedical\b|\bhospital\b|\bdisease\b|\bvaccine\b|\bwho\b"),
        ("science", r"วิทยาศาสตร์|อวกาศ|ดาราศาสตร์|นาซา|นาซ่า|สิ่งแวดล้อม|โลกร้อน|สภาพภูมิอากาศ|แผ่นดินไหว|พายุ|น้ำท่วม|\bscience\b|\bspace\b|\bnasa\b|\bclimate\b|\bresearch\b|\bearthquake\b"),
        ("culture", r"บันเทิง|ดารา|นักแสดง|ภาพยนตร์|หนังใหม่|เพลงใหม่|คอนเสิร์ต|ซีรีส์|ละคร|เกมใหม่|\bentertainment\b|\bculture\b|\bfilm\b|\bmovie\b|\bmusic\b|\bcelebrity\b|\btelevision\b"),
    )
    for category, pattern in topic_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return category
    return fallback


def _fetch_feed(feed):
    request = Request(
        feed["url"],
        headers={"User-Agent": "SatoshiCoreToday/1.0 (+https://chat.satoshicore.org)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"},
    )
    with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
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
        source_node = next((child for child in entry if _local_name(child.tag) == "source"), None)
        source_name = _plain_text("".join(source_node.itertext()), 120) if source_node is not None else ""
        if source_name and title.casefold().endswith(f" - {source_name}".casefold()):
            title = title[: -(len(source_name) + 3)].strip()
        published = _published_at(entry)
        if not title or not link or not published:
            continue
        if feed.get("media_type") == "VIDEO":
            if published < timezone.now() - timedelta(days=7):
                continue
        elif published.astimezone(BANGKOK_TZ).date() != today:
            continue
        if link in seen:
            continue
        seen.add(link)
        summary = _plain_text(_child_text(entry, "description", "summary", "content"), 1000) if feed.get("summary", True) else ""
        category = _classify_headline(title, feed["category"]) if feed.get("classify", False) else feed["category"]
        image_url = _entry_image(entry)
        video_url = _entry_video(entry) or (link if feed.get("media_type") == "VIDEO" else "")
        category_label = f"{CATEGORY_LABELS[category]} video" if feed.get("media_type") == "VIDEO" else CATEGORY_LABELS[category]
        items.append({
            "id": link,
            "title": title,
            "summary": summary,
            "image_url": image_url,
            "video_url": video_url,
            "media_type": feed.get("media_type", "ARTICLE"),
            "url": link,
            "source": source_name or feed["label"],
            "category": category,
            "category_label": category_label,
            "region": feed.get("region", "world"),
            "region_label": CATEGORY_LABELS.get(feed.get("region", "world"), "World"),
            "published_at": published.isoformat(),
        })
        if len(items) >= MAX_ITEMS_PER_FEED:
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
    with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
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
        category = _classify_headline(title, "thailand" if country in {"th", "thailand"} else "world")
        items.append({
            "id": link,
            "title": title,
            "summary": "",
            "url": link,
            "source": domain,
            "category": category,
            "category_label": CATEGORY_LABELS[category],
            "region": "thailand" if country in {"th", "thailand"} else "world",
            "region_label": "Thailand" if country in {"th", "thailand"} else "World",
            "published_at": published.isoformat(),
        })
    return items


def _fetch_today_items():
    items = []
    failures = 0
    successful_sources = set()
    with ThreadPoolExecutor(max_workers=len(FEEDS) + 1) as executor:
        future_sources = {executor.submit(_fetch_feed, feed): feed for feed in FEEDS}
        future_sources[executor.submit(_fetch_global_news)] = {"label": "GDELT Project", "region": "world", "global_source": True}
        successful_global_source = False
        successful_thailand_source = False
        for future in as_completed(future_sources):
            try:
                result = future.result()
                items.extend(result)
                source = future_sources[future]
                successful_sources.add(source["label"])
                successful_global_source |= source.get("global_source", False)
                successful_thailand_source |= source.get("region") == "thailand"
            except Exception:
                failures += 1
    if failures == len(FEEDS) + 1:
        raise URLError("All configured Today news sources are unavailable")
    unique = {item["url"]: item for item in items}
    items = _balance_categories(_rank_coverage(unique.values()))[:MAX_ITEMS]
    today = _today_bangkok()
    source_label = " · ".join(sorted(successful_sources)) or FEED_LABEL
    return {
        "items": items,
        "source": source_label,
        "sources": sorted(successful_sources),
        "global_available": successful_global_source,
        "thailand_available": successful_thailand_source,
        "global_trends_available": "GDELT Project" in successful_sources,
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


def _balance_categories(items):
    """Interleave fresh headlines so one high-volume feed cannot crowd out other topics."""
    categories = {}
    for item in items:
        categories.setdefault(item.get("category", "world"), []).append(item)
    ordered_categories = ["thailand", "world", "business", "technology", "science", "health", "sports", "culture"]
    ordered_categories.extend(category for category in categories if category not in ordered_categories)
    balanced = []
    for category in ordered_categories:
        category_items = categories.get(category, [])
        selected = category_items[:MAX_ITEMS_PER_CATEGORY]
        # Preserve publisher videos for the mixed Social feed even when a
        # category has more than the normal headline cap.
        video = next((item for item in category_items if item.get("media_type") == "VIDEO"), None)
        if video and video not in selected:
            if selected:
                selected[-1] = video
            else:
                selected = [video]
        balanced.extend(selected)
    return balanced


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
        allowed = {"all", *CATEGORY_LABELS}
        if category not in allowed:
            category = "all"
        items = feed.get("items", [])
        if category != "all":
            items = [item for item in items if item.get("category") == category or item.get("region") == category]
        if query:
            items = [
                item for item in items
                if query in f"{item.get('title', '')} {item.get('summary', '')}".casefold()
            ]
        available_categories = {
            category
            for item in feed.get("items", [])
            for category in (item.get("category"), item.get("region"))
            if category in CATEGORY_LABELS
        }
        return {
            **feed,
            "items": items,
            "stale": stale,
            "categories": [
                {"id": "all", "label": "All"},
                *[
                    {"id": category, "label": label}
                    for category, label in CATEGORY_LABELS.items()
                    if category in available_categories
                ],
            ],
        }
