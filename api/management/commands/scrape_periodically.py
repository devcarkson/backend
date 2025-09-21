import time
from datetime import datetime

from django.core.management.base import BaseCommand

from api.models import Article


class Command(BaseCommand):
    help = 'Run periodic article scraping every 5 minutes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=300,  # 5 minutes
            help='Scraping interval in seconds (default: 300)',
        )

    def handle(self, *args, **options):
        interval = options['interval']
        self.stdout.write(f'Starting periodic scraping every {interval} seconds...')

        # Wait for the first interval before starting the loop to avoid slowing down app startup
        self.stdout.write(f'Waiting {interval} seconds before first scraping cycle...')
        time.sleep(interval)

        while True:
            try:
                self.stdout.write(f'[{datetime.now()}] Starting scraping cycle...')

                # Get all unscraped articles
                unscraped_urls = list(Article.objects.filter(is_scraped=False).values_list('url', flat=True))

                # Scrape unscraped articles
                if unscraped_urls:
                    self.stdout.write(f'Found {len(unscraped_urls)} unscraped articles')

                    # Scrape them
                    from django.core.management import call_command
                    call_command('scrape_articles', urls=unscraped_urls)

                # Also update old articles
                from django.core.management import call_command
                call_command('scrape_articles', update_old=True)

                # Fetch new articles from RSS feeds
                self.stdout.write('Fetching new articles from RSS feeds...')
                from api.views import FEEDS, _parse_feeds
                new_articles_count = 0
                for category, feeds in FEEDS.items():
                    try:
                        self.stdout.write(f'Fetching {category} news...')
                        items = _parse_feeds(feeds, category, limit=20)  # Fetch up to 20 new articles per category
                        new_articles_count += len(items)
                        self.stdout.write(f'Fetched {len(items)} new {category} articles')
                    except Exception as e:
                        self.stdout.write(f'Error fetching {category} news: {str(e)}')

                self.stdout.write(f'Fetched {new_articles_count} new articles from RSS feeds')

                self.stdout.write(f'[{datetime.now()}] Scraping cycle completed')

                # Wait for next cycle
                self.stdout.write(f'Waiting {interval} seconds until next cycle...')
                time.sleep(interval)

            except KeyboardInterrupt:
                self.stdout.write('Stopping periodic scraping...')
                break
            except Exception as e:
                self.stdout.write(f'Error in scraping cycle: {str(e)}')
                time.sleep(interval)