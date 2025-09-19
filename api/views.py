import base64
import random
import re
from datetime import datetime
from typing import List, Dict

import feedparser
import requests
from django.http import JsonResponse
from django.views.decorators.http import require_GET


def _encode_id(link: str) -> str:
    return base64.urlsafe_b64encode(link.encode()).decode().rstrip('=')


def _decode_id(item_id: str) -> str:
    pad = '=' * (-len(item_id) % 4)
    return base64.urlsafe_b64decode((item_id + pad).encode()).decode()


def _estimate_read_time(text: str) -> str:
    words = max(1, len(text.split()))
    minutes = max(1, int(words / 200))
    return f"{minutes} min read"


def _pick_image(entry) -> str:
    # Try typical media fields
    media_content = entry.get('media_content') or []
    if media_content and isinstance(media_content, list):
        url = media_content[0].get('url')
        if url:
            return url
    media_thumbnail = entry.get('media_thumbnail') or []
    if media_thumbnail and isinstance(media_thumbnail, list):
        url = media_thumbnail[0].get('url')
        if url:
            return url
    # Fall back to image link fields
    for key in ['image', 'thumbnail', 'cover', 'logo']:
        val = entry.get(key)
        if isinstance(val, str):
            return val
        if isinstance(val, dict) and val.get('href'):
            return val['href']
    # As a last resort, use a placeholder
    return 'https://picsum.photos/seed/news/800/400'


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
                        published_iso = dt.isoformat() + 'Z'
                    elif published:
                        published_iso = published
                    else:
                        published_iso = datetime.utcnow().isoformat() + 'Z'
                except Exception as ex:
                    print(f"Error parsing published date: {ex}")
                    published_iso = datetime.utcnow().isoformat() + 'Z'
                item = {
                    'id': _encode_id(link),
                    'title': title,
                    'excerpt': summary and re.sub('<[^<]+?>', '', summary)[:240],
                    'image': _pick_image(e),
                    'source': source_title,
                    'publishedAt': published_iso,
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
    if category == 'all':
        all_items = []
        for cat, feeds in FEEDS.items():
            all_items.extend(_parse_feeds(feeds, cat, limit=limit))
        # sort and slice
        all_items.sort(key=lambda x: x['publishedAt'], reverse=True)
        return JsonResponse({'results': all_items[:limit]}, safe=False)
    feeds = FEEDS.get(category, FEEDS['world'])
    items = _parse_feeds(feeds, category, limit=limit)
    return JsonResponse({'results': items})


@require_GET
def news_detail(request, item_id: str):
    # Decode ID back to link and return basic info; full scraping is out of scope.
    try:
        link = _decode_id(item_id)
    except Exception:
        return JsonResponse({'error': 'Invalid id'}, status=400)
    return JsonResponse({'id': item_id, 'link': link})


@require_GET
def trending(request):
    items = []
    for cat, feeds in FEEDS.items():
        items.extend(_parse_feeds(feeds, cat, limit=5))
    # Shuffle and slice
    random.shuffle(items)
    items = items[:10]
    # Transform for sidebar
    simplified = [
        {
            'id': it['id'],
            'title': it['title'],
            'views': f"{random.randint(100, 2000)}K",
            'timeAgo': 'recent',
            'source': it['source'],
            'trending': it.get('trending', False),
        }
        for it in items
    ]
    return JsonResponse({'results': simplified})


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
    country = request.GET.get('country', 'US')
    params = {
        'term': term,
        'media': 'music',
        'limit': min(limit, 50),
        'country': country,
    }
    r = requests.get(ITUNES_SEARCH, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    tracks = [_normalize_track(t) for t in data.get('results', []) if t.get('trackId')]
    for t in tracks[: min(4, len(tracks))]:
        t['featured'] = True
    return JsonResponse({'results': tracks})


@require_GET
def music_detail(request, track_id: int):
    params = {'id': track_id}
    r = requests.get(ITUNES_LOOKUP, params=params, timeout=10)
    if r.status_code != 200:
        return JsonResponse({'error': 'Track not found'}, status=404)
    results = r.json().get('results', [])
    if not results:
        return JsonResponse({'error': 'Track not found'}, status=404)
    track = _normalize_track(results[0])
    # add some related tracks by same artist
    artist = results[0].get('artistName')
    rel = requests.get(ITUNES_SEARCH, params={'term': artist, 'media': 'music', 'limit': 5}, timeout=10)
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
    return JsonResponse(track)
