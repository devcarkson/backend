import os
import threading
from django.apps import AppConfig
from django.core.management import call_command


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        # Only start the scraper in production or if explicitly enabled
        if os.environ.get('START_PERIODIC_SCRAPER', 'False').lower() == 'true':
            # Start the periodic scraper in a background thread
            scraper_thread = threading.Thread(target=self._start_periodic_scraper, daemon=True)
            scraper_thread.start()

    def _start_periodic_scraper(self):
        """Start the periodic scraper in a separate thread"""
        try:
            from django.core.management import execute_from_command_line
            # Run the scrape_periodically command
            execute_from_command_line(['manage.py', 'scrape_periodically'])
        except Exception as e:
            # Log the error but don't crash the app
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to start periodic scraper: {e}")
