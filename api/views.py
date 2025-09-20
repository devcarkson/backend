import base64
import random
import re
from datetime import datetime, timezone as dt_timezone
from typing import List, Dict

import feedparser
import requests
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone as django_timezone
from django.views.decorators.http import require_GET
from .models import Article


def _encode_id(link: str) -> str:
    return base64.urlsafe_b64encode(link.encode()).decode().rstrip('=')


def _decode_id(item_id: str) -> str:
    pad = '=' * (-len(item_id) % 4)
    return base64.urlsafe_b64decode((item_id + pad).encode()).decode()


def _estimate_read_time(text: str) -> str:
    words = max(1, len(text.split()))
    minutes = max(1, int(words / 200))
    return f"{minutes} min read"


def _format_datetime(dt) -> str:
    """Format datetime for frontend consumption"""
    if not dt:
        return None

    # Ensure datetime is timezone-aware
    if dt.tzinfo is None:
        dt = django_timezone.make_aware(dt)

    # Convert to UTC for consistent API responses
    dt_utc = dt.astimezone(dt_timezone.utc)

    # Return ISO format with Z suffix (standard for UTC)
    return dt_utc.isoformat().replace('+00:00', 'Z')

# Simple OG image cache and scraper for whitelisted domains
_OG_CACHE: Dict[str, str] = {}
_ARTICLE_CACHE: Dict[str, Dict] = {}
_SCRAPE_WHITELIST = (
    'espn.com', 'www.espn.com',
    'techcrunch.com', 'www.techcrunch.com',
    'aljazeera.com', 'www.aljazeera.com'
)

def _scrape_og_image(url: str) -> str | None:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ''
        if not any(host.endswith(d) for d in _SCRAPE_WHITELIST):
            return None
        if url in _OG_CACHE:
            return _OG_CACHE[url]
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=4)
        if resp.status_code != 200:
            return None
        html = resp.text
        import re
        # look for og:image then twitter:image, then link rel=image_src
        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
            r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)',
        ]
        for pat in patterns:
            m = re.search(pat, html, flags=re.IGNORECASE)
            if m:
                src = m.group(1)
                if src.startswith('//'):
                    src = 'https:' + src
                if src.startswith('http'):
                    _OG_CACHE[url] = src
                    return src
        return None
    except Exception:
        return None


def _scrape_article_content(url: str) -> Dict | None:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ''
        if not any(host.endswith(d) for d in _SCRAPE_WHITELIST):
            return None

        if url in _ARTICLE_CACHE:
            return _ARTICLE_CACHE[url]

        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None

        html = resp.text

        # Extract title
        title = None
        title_patterns = [
            r'<title[^>]*>([^<]+)</title>',
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
            r'<h1[^>]*>([^<]+)</h1>',
        ]
        for pat in title_patterns:
            m = re.search(pat, html, flags=re.IGNORECASE)
            if m:
                title = m.group(1).strip()
                break

        # Extract article content - try multiple approaches
        content = None

        # First try to find main article containers
        content_selectors = [
            r'<article[^>]*>(.*?)</article>',
            r'<div[^>]*class=["\'][^"\']*article[^"\']*["\'][^>]*>(.*?)</div>',
            r'<div[^>]*class=["\'][^"\']*content[^"\']*["\'][^>]*>(.*?)</div>',
            r'<div[^>]*class=["\'][^"\']*post[^"\']*["\'][^>]*>(.*?)</div>',
            r'<div[^>]*id=["\'][^"\']*content[^"\']*["\'][^>]*>(.*?)</div>',
            r'<div[^>]*id=["\'][^"\']*article[^"\']*["\'][^>]*>(.*?)</div>',
        ]

        for pat in content_selectors:
            m = re.search(pat, html, flags=re.IGNORECASE | re.DOTALL)
            if m:
                raw_content = m.group(1)
                # Remove scripts and styles
                raw_content = re.sub(r'<script[^>]*>.*?</script>', '', raw_content, flags=re.IGNORECASE | re.DOTALL)
                raw_content = re.sub(r'<style[^>]*>.*?</style>', '', raw_content, flags=re.IGNORECASE | re.DOTALL)
                # Extract text from paragraphs and other elements
                paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', raw_content, flags=re.IGNORECASE | re.DOTALL)
                if paragraphs:
                    content = ' '.join(re.sub(r'<[^>]+>', '', p).strip() for p in paragraphs if p.strip())
                else:
                    # Fallback to general text extraction
                    content = re.sub(r'<[^>]+>', '', raw_content).strip()
                if len(content) > 200:  # Require more substantial content
                    break

        # If no content found with selectors, try extracting all paragraphs from the page
        if not content or len(content) < 200:
            all_paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, flags=re.IGNORECASE | re.DOTALL)
            if all_paragraphs:
                content = ' '.join(re.sub(r'<[^>]+>', '', p).strip() for p in all_paragraphs if p.strip() and len(p.strip()) > 20)

        if title or content:
            article_data = {
                'title': title,
                'content': content,
                'scraped': True
            }
            _ARTICLE_CACHE[url] = article_data
            return article_data
        return None
    except Exception:
        return None


def _pick_image(entry, category: str) -> str:
    """Pick a representative image for a feed entry, avoiding generic logos.
    Strategy:
    1) Collect candidates from media:content, media:thumbnail, link enclosures, and inline HTML images.
    2) Prefer non-generic images (skip logos/sprites/icons/placeholders) and normalize protocol-relative URLs.
    3) Fallback to the first valid candidate, else category-specific placeholder.
    """
    import re

    def norm(u: str | None) -> str | None:
        if not u:
            return None
        if u.startswith('//'):
            return 'https:' + u
        return u

    def is_valid(u: str | None) -> bool:
        if not u:
            return False
        u = u.lower()
        return u.startswith('http://') or u.startswith('https://') or u.startswith('//')

    def is_generic(u: str) -> bool:
        s = u.lower()
        # common generic/logo patterns seen across feeds (esp. ESPN)
        generic_keywords = [
            'logo', 'sprite', 'icon', 'placeholder', 'default', 'branding', 'og-default',
            '/i/espn/', 'espn_logo', 'branding.svg', 'favicon', 'badge'
        ]
        if any(k in s for k in generic_keywords):
            return True
        # too small images (thumbnails or tracking pixels)
        if re.search(r'[\?&]w=\d{1,2}(?:&|$)', s):
            return True
        return False

    candidates: list[str] = []

    # media:content and media:thumbnail
    media_content = entry.get('media_content') or []
    if isinstance(media_content, list):
        for mc in media_content:
            u = mc.get('url')
            if is_valid(u):
                candidates.append(u)
    media_thumbnail = entry.get('media_thumbnail') or []
    if isinstance(media_thumbnail, list):
        for mt in media_thumbnail:
            u = mt.get('url')
            if is_valid(u):
                candidates.append(u)

    # enclosures/links with image type or extension
    links = entry.get('links') or []
    if isinstance(links, list):
        for l in links:
            try:
                rel = (l.get('rel') or '').lower()
                href = l.get('href')
                typ = (l.get('type') or '').lower()
                if is_valid(href) and (rel == 'enclosure' or 'image' in typ or str(href).lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))):
                    candidates.append(href)
            except Exception:
                continue

    # first <img src> in content/summary/description
    def first_img(html: str) -> str | None:
        m = re.search(r'<img[^>]+src=["\']([^"\']+)', html or '', flags=re.IGNORECASE)
        if not m:
            return None
        src = m.group(1)
        if src.startswith('data:'):
            return None
        return src

    content = entry.get('content') or []
    if isinstance(content, list) and content:
        html = content[0].get('value') or ''
        img = first_img(html)
        if is_valid(img):
            candidates.append(img) 
    for key in ['summary', 'description']:
        html = entry.get(key) or ''
        if isinstance(html, str):
            img = first_img(html)
            if is_valid(img):
                candidates.append(img)

    # choose first non-generic candidate
    for u in candidates:
        nu = norm(u) or ''
        if not is_generic(nu):
            return nu

    # try scraping og:image for known domains if candidates are generic
    link = entry.get('link') or ''
    og = _scrape_og_image(link)
    if og:
        return og

    # otherwise return first valid candidate if any
    if candidates:
        return norm(candidates[0]) or candidates[0]

    # Fallback to a category-specific placeholder
    seed = (category or 'news').lower().replace(' ', '-')
    return f'https://picsum.photos/seed/{seed}-news/800/400'


FEEDS = {
    'world': [
        'http://feeds.bbci.co.uk/news/world/rss.xml',
        'https://www.aljazeera.com/xml/rss/all.xml',
    ],
    'technology': [
        'https://techcrunch.com/feed/',
        'https://www.theverge.com/rss/index.xml',
    ],
    'sports': [
        'https://www.espn.com/espn/rss/news',
        'http://feeds.bbci.co.uk/sport/rss.xml?edition=uk',
    ],
    'entertainment': [
        'https://www.theguardian.com/culture/rss',
        'https://variety.com/feed/',
    ],
    'nigeria': [
        'https://www.channelstv.com/feed/',
        'https://punchng.com/feed/',
        'https://www.vanguardngr.com/feed/',
      ],
}


def _parse_feeds(feeds: List[str], category: str, limit: int = 12) -> List[Dict]:
    items: List[Dict] = []
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
            source_title = parsed.feed.get('title', 'Source')
            for e in parsed.entries:
                link = e.get('link', '')
                if not link:
                    continue
                title = e.get('title', 'Untitled')
                summary = e.get('summary', '') or e.get('description', '')
                published = e.get('published') or e.get('updated')
                try:
                    # Try to parse published date
                    if 'published_parsed' in e and e.published_parsed:
                        dt = datetime(*e.published_parsed[:6])
                        published_at = dt
                    elif published:
                        # Try to parse the published string
                        try:
                            from email.utils import parsedate_to_datetime
                            published_at = parsedate_to_datetime(published)
                        except:
                            published_at = django_timezone.now()
                    else:
                        published_at = django_timezone.now()
                except Exception as ex:
                    print(f"Error parsing published date: {ex}")
                    published_at = django_timezone.now()
                # Save to database
                article, created = Article.objects.get_or_create(
                    url=link,
                    defaults={
                        'title': title,
                        'excerpt': summary and re.sub('<[^<]+?>', '', summary)[:240],
                        'author': getattr(e, 'author', '') or '',
                        'published_at': published_at,
                        'source': source_title,
                        'category': category.capitalize(),
                        'read_time': _estimate_read_time(summary or title),
                        'image': _pick_image(e, category),
                    }
                )

                item = {
                    'id': _encode_id(link),
                    'title': title,
                    'excerpt': summary and re.sub('<[^<]+?>', '', summary)[:240],
                    'image': _pick_image(e, category),
                    'source': source_title,
                    'publishedAt': _format_datetime(published_at),
                    'trending': False,
                    'author': getattr(e, 'author', None),
                    'category': category.capitalize(),
                    'readTime': _estimate_read_time(summary or title),
                    'link': link,
                }
                items.append(item)
        except Exception as ex:
            print(f"Error parsing feed {url}: {ex}")
            continue
    # Deduplicate by link id preserving order
    seen = set()
    deduped = []
    for it in items:
        if it['id'] in seen:
            continue
        seen.add(it['id'])
        deduped.append(it)
    deduped.sort(key=lambda x: x['publishedAt'], reverse=True)
    # Mark some as trending
    for it in deduped[: min(5, len(deduped))]:
        it['trending'] = True
    return deduped[:limit]


@require_GET
def news_list(request):
    category = request.GET.get('category', 'world').lower()
    limit = int(request.GET.get('limit', '12'))
    offset = int(request.GET.get('offset', '0'))
    key = f"news_{category}_{limit}_{offset}"
    cached = cache.get(key)
    if cached:
        return JsonResponse({'results': cached})

    # Query database instead of parsing RSS feeds
    queryset = Article.objects.all()

    if category != 'all':
        queryset = queryset.filter(category__iexact=category.capitalize())

    # Get total count for pagination info
    total_count = queryset.count()

    # Order by published date and apply pagination
    articles = queryset.order_by('-published_at')[offset:offset + limit]

    results = []
    for article in articles:
        item = {
            'id': _encode_id(article.url),
            'title': article.title,
            'excerpt': article.excerpt,
            'image': article.image,
            'source': article.source,
            'publishedAt': _format_datetime(article.published_at),
            'trending': False,  # Could be determined by view count or other metrics
            'author': article.author,
            'category': article.category,
            'readTime': article.read_time,
            'link': article.url,
        }
        results.append(item)

    # Mark some as trending (first few)
    for item in results[:min(5, len(results))]:
        item['trending'] = True

    # If no articles in database, trigger RSS parsing
    if not results:
        # Fallback to RSS parsing to populate database
        if category == 'all':
            all_items = []
            for cat, feeds in FEEDS.items():
                all_items.extend(_parse_feeds(feeds, cat, limit=100))
            # Sort by publishedAt (which is now a string, so we need to handle that)
            all_items.sort(key=lambda x: x.get('publishedAt', ''), reverse=True)
            results = all_items[offset:offset + limit]
        else:
            feeds = FEEDS.get(category, FEEDS['world'])
            all_items = _parse_feeds(feeds, category, limit=100)
            results = all_items[offset:offset + limit]

    cache.set(key, results, 300)  # Cache for 5 minutes
    return JsonResponse({'results': results})


@require_GET
def news_detail(request, item_id: str):
    key = f"news_detail_{item_id}"
    cached = cache.get(key)
    if cached:
        return JsonResponse(cached)

    try:
        link = _decode_id(item_id)
    except Exception:
        return JsonResponse({'error': 'Invalid id'}, status=400)

    # Try to get from database first
    try:
        article = Article.objects.get(url=link)
        if article.is_scraped and article.content:
            response_data = {
                'id': item_id,
                'link': link,
                'title': article.title,
                'content': article.content,
                'scraped': True,
                'author': article.author,
                'publishedAt': _format_datetime(article.published_at),
                'source': article.source,
                'category': article.category,
                'readTime': article.read_time,
                'image': article.image,
            }
        else:
            # Article exists but not scraped, trigger background scraping
            from django.core.management import call_command
            from threading import Thread
            def scrape_async():
                call_command('scrape_articles', urls=[link])
            thread = Thread(target=scrape_async)
            thread.daemon = True
            thread.start()

            response_data = {
                'id': item_id,
                'link': link,
                'title': article.title,
                'excerpt': article.excerpt,
                'author': article.author,
                'publishedAt': _format_datetime(article.published_at),
                'source': article.source,
                'category': article.category,
                'readTime': article.read_time,
                'image': article.image,
            }
    except Article.DoesNotExist:
        # Article not in database, create it and trigger scraping
        article = Article.objects.create(url=link)
        from django.core.management import call_command
        from threading import Thread
        def scrape_async():
            call_command('scrape_articles', urls=[link])
        thread = Thread(target=scrape_async)
        thread.daemon = True
        thread.start()

        response_data = {'id': item_id, 'link': link}

    cache.set(key, response_data, 300)  # Cache for 5 minutes
    return JsonResponse(response_data)


@require_GET
def trending(request):
    key = "trending"
    cached = cache.get(key)
    if cached:
        return JsonResponse({'results': cached})

    # Get trending articles from database
    articles = Article.objects.all().order_by('-published_at')[:20]

    if not articles:
        # Fallback to RSS parsing if no articles in database
        items = []
        for cat, feeds in FEEDS.items():
            items.extend(_parse_feeds(feeds, cat, limit=5))
        # Shuffle and slice
        random.shuffle(items)
        items = items[:10]
    else:
        # Convert articles to the expected format
        items = []
        for article in articles[:10]:
            items.append({
                'id': _encode_id(article.url),
                'title': article.title,
                'views': f"{random.randint(100, 2000)}K",
                'timeAgo': 'recent',
                'source': article.source,
                'trending': True,
                'publishedAt': _format_datetime(article.published_at),
            })

    cache.set(key, items, 300)  # Cache for 5 minutes
    return JsonResponse({'results': items})


ITUNES_SEARCH = 'https://itunes.apple.com/search'
ITUNES_LOOKUP = 'https://itunes.apple.com/lookup'


def _normalize_track(t):
    duration_ms = t.get('trackTimeMillis') or 0
    minutes = duration_ms // 60000
    seconds = (duration_ms % 60000) // 1000
    duration = f"{minutes}:{seconds:02d}" if duration_ms else None
    return {
        'id': t.get('trackId'),
        'title': t.get('trackName'),
        'artist': t.get('artistName'),
        'album': t.get('collectionName'),
        'duration': duration or '3:00',
        'genre': t.get('primaryGenreName'),
        'rating': round(4.2 + random.random() * 0.6, 1),
        'downloads': random.randint(3000, 20000),
        'image': t.get('artworkUrl100') or t.get('artworkUrl60') or 'https://picsum.photos/seed/music/300/300',
        'featured': False,
        'audioUrl': t.get('previewUrl'),
        'releaseDate': t.get('releaseDate', '')[:10],
        'likes': random.randint(200, 5000),
    }


@require_GET
def music_search(request):
    term = request.GET.get('term', 'top hits')
    limit = int(request.GET.get('limit', '24'))
    offset = int(request.GET.get('offset', '0'))
    country = request.GET.get('country', 'US')
    key = f"music_search_{term}_{limit}_{offset}_{country}"
    cached = cache.get(key)
    if cached:
        return JsonResponse({'results': cached})
    params = {
        'term': term,
        'media': 'music',
        'limit': min(limit + offset, 50),  # Get more to handle offset
        'country': country,
    }
    r = requests.get(ITUNES_SEARCH, params=params)
    r.raise_for_status()
    data = r.json()
    all_tracks = [_normalize_track(t) for t in data.get('results', []) if t.get('trackId')]
    tracks = all_tracks[offset:offset + limit]
    for t in tracks[: min(4, len(tracks))]:
        t['featured'] = True
    cache.set(key, tracks, 300)  # Cache for 5 minutes
    return JsonResponse({'results': tracks})


@require_GET
def music_detail(request, track_id: int):
    key = f"music_detail_{track_id}"
    cached = cache.get(key)
    if cached:
        return JsonResponse(cached)
    params = {'id': track_id}
    r = requests.get(ITUNES_LOOKUP, params=params)
    if r.status_code != 200:
        return JsonResponse({'error': 'Track not found'}, status=404)
    results = r.json().get('results', [])
    if not results:
        return JsonResponse({'error': 'Track not found'}, status=404)
    track = _normalize_track(results[0])
    # add some related tracks by same artist
    artist = results[0].get('artistName')
    rel = requests.get(ITUNES_SEARCH, params={'term': artist, 'media': 'music', 'limit': 5})
    related = []
    if rel.status_code == 200:
        for t in rel.json().get('results', [])[:5]:
            if t.get('trackId') == track_id:
                continue
            related.append({
                'id': t.get('trackId'),
                'title': t.get('trackName'),
                'artist': t.get('artistName'),
                'duration': _normalize_track(t)['duration'],
                'image': t.get('artworkUrl60') or t.get('artworkUrl100'),
            })
    track['relatedTracks'] = related
    cache.set(key, track, 300)  # Cache for 5 minutes
    return JsonResponse(track)
