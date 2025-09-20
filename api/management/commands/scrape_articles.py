import re
from urllib.parse import urlparse

import requests
from django.core.management.base import BaseCommand

from api.models import Article


class Command(BaseCommand):
    help = 'Scrape article content from URLs and save to database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--urls',
            nargs='+',
            type=str,
            help='Specific URLs to scrape',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Scrape all articles in database that haven\'t been scraped yet',
        )
        parser.add_argument(
            '--update-old',
            action='store_true',
            help='Update articles that were scraped more than 1 hour ago',
        )

    def handle(self, *args, **options):
        if options['urls']:
            urls = options['urls']
        elif options['all']:
            urls = list(Article.objects.filter(is_scraped=False).values_list('url', flat=True))
        elif options['update_old']:
            from datetime import timedelta
            from django.utils import timezone
            one_hour_ago = timezone.now() - timedelta(hours=1)
            urls = list(Article.objects.filter(
                scraped_at__lt=one_hour_ago
            ).values_list('url', flat=True))
        else:
            self.stdout.write('Please specify --urls, --all, or --update-old')
            return

        scraped_count = 0
        for url in urls:
            try:
                self.stdout.write(f'Scraping: {url}')
                article_data = self._scrape_article_content(url)
                if article_data:
                    Article.objects.filter(url=url).update(
                        title=article_data.get('title', ''),
                        content=article_data.get('content', ''),
                        is_scraped=True
                    )
                    scraped_count += 1
                    self.stdout.write(f'Successfully scraped: {url}')
                else:
                    self.stdout.write(f'Failed to scrape: {url}')
            except Exception as e:
                self.stdout.write(f'Error scraping {url}: {str(e)}')

        self.stdout.write(f'Scraped {scraped_count} articles successfully')

    def _scrape_article_content(self, url):
        SCRAPE_WHITELIST = (
            'espn.com', 'www.espn.com',
            'techcrunch.com', 'www.techcrunch.com',
            'aljazeera.com', 'www.aljazeera.com'
        )

        try:
            host = urlparse(url).hostname or ''
            if not any(host.endswith(d) for d in SCRAPE_WHITELIST):
                return None

            headers = {'User-Agent': 'FeedScribe/1.0'}
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

            # Extract article content
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
                return {
                    'title': title,
                    'content': content,
                }
            return None
        except Exception:
            return None