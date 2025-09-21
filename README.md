# News Aggregator API

A Django-based REST API for aggregating news articles from RSS feeds, scraping article content, and providing music search functionality via iTunes API.

## Features

- **News Aggregation**: Fetches articles from multiple RSS feeds across categories (World, Technology, Sports, Entertainment, Nigeria)
- **Article Scraping**: Automatically scrapes full article content from whitelisted domains (ESPN, TechCrunch, Al Jazeera)
- **Periodic Updates**: Background scraper that runs every 5 minutes to update articles and fetch new content
- **Music Search**: Integration with iTunes API for music search and details
- **Caching**: Built-in caching for improved performance
- **CORS Support**: Configured for frontend integration
- **RESTful API**: JSON-based API with pagination support

## Installation

### Prerequisites

- Python 3.8+
- pip
- Virtual environment (recommended)

### Setup

1. **Clone the repository** (if applicable) or navigate to the project directory

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**:
   Create a `.env` file in the project root with the following variables:
   ```env
   DJANGO_SECRET_KEY=your-secret-key-here
   DJANGO_DEBUG=True
   DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,your-domain.com
   CORS_ALLOW_ALL=True
   CORS_ALLOWED_ORIGINS=http://127.0.0.1:3000,https://your-frontend-domain.com
   CSRF_TRUSTED_ORIGINS=https://your-frontend-domain.com
   ```

5. **Run database migrations**:
   ```bash
   python manage.py migrate
   ```

6. **Create a superuser** (optional, for Django admin):
   ```bash
   python manage.py createsuperuser
   ```

## Usage

### Running the Development Server

```bash
python manage.py runserver
```

The API will be available at `http://127.0.0.1:8000/api/`

### Running the Periodic Scraper

The periodic scraper runs automatically every 5 minutes to:
- Scrape unscraped articles
- Update existing articles
- Fetch new articles from RSS feeds

#### Automatic Startup
To start the scraper automatically when the Django application starts, set the environment variable:
```env
START_PERIODIC_SCRAPER=True
```

**Note:** This is recommended for production deployments where you want continuous background scraping. In development, you may prefer to run it manually.

#### Manual Execution
To run it manually:
```bash
python manage.py scrape_periodically
```

To customize the interval:
```bash
python manage.py scrape_periodically --interval=600  # 10 minutes
```

### Running with Gunicorn (Production)

```bash
gunicorn app:app --bind 0.0.0.0:8000
```

## API Endpoints

### News Endpoints

- **GET /api/news** - List news articles
  - Query parameters:
    - `category`: Filter by category (world, technology, sports, entertainment, nigeria, all)
    - `limit`: Number of articles to return (default: 12)
    - `offset`: Pagination offset (default: 0)

- **GET /api/news/{item_id}** - Get detailed article information
  - Includes full scraped content if available

- **GET /api/trending** - Get trending articles

### Music Endpoints

- **GET /api/music** - Search music tracks
  - Query parameters:
    - `term`: Search term
    - `limit`: Number of results (default: 24)
    - `offset`: Pagination offset (default: 0)
    - `country`: Country code (default: US)

- **GET /api/music/{track_id}** - Get detailed track information

### Example API Responses

#### News List
```json
{
  "results": [
    {
      "id": "encoded-url-id",
      "title": "Article Title",
      "excerpt": "Article excerpt...",
      "image": "https://example.com/image.jpg",
      "source": "BBC News",
      "publishedAt": "2024-01-15T10:30:00Z",
      "trending": true,
      "author": "John Doe",
      "category": "World",
      "readTime": "5 min read",
      "link": "https://example.com/article"
    }
  ]
}
```

#### News Detail
```json
{
  "id": "encoded-url-id",
  "link": "https://example.com/article",
  "title": "Article Title",
  "content": "Full article content...",
  "scraped": true,
  "author": "John Doe",
  "publishedAt": "2024-01-15T10:30:00Z",
  "source": "BBC News",
  "category": "World",
  "readTime": "5 min read",
  "image": "https://example.com/image.jpg"
}
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DJANGO_SECRET_KEY` | Django secret key | dev-secret-key-change-me |
| `DJANGO_DEBUG` | Enable/disable debug mode | True |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated list of allowed hosts | * |
| `CORS_ALLOW_ALL` | Allow all CORS origins | True |
| `CORS_ALLOWED_ORIGINS` | Comma-separated list of allowed CORS origins | (empty) |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated list of trusted CSRF origins | (empty) |
| `START_PERIODIC_SCRAPER` | Automatically start the periodic scraper when the app starts | False |

## Database

The project uses SQLite by default. To use a different database, modify the `DATABASES` setting in `core/settings.py`.

## Deployment

### Local Development
Follow the installation steps above.

### Production Deployment
1. Set `DJANGO_DEBUG=False`
2. Use a production WSGI server like Gunicorn
3. Configure a reverse proxy (nginx/Apache)
4. Set up proper environment variables
5. Run database migrations
6. Collect static files: `python manage.py collectstatic`

### Running scrape_periodically.py in Shared Hosting (cPanel)

Shared hosting environments like cPanel have limitations that make running long-running processes like the periodic scraper challenging:

#### Limitations:
- **No persistent processes**: cPanel typically terminates long-running scripts after a few minutes
- **No cron job support**: Some shared hosts don't provide cron job access
- **Resource restrictions**: Limited CPU/memory for background tasks
- **Timeout issues**: Scripts may timeout before completing

#### Recommended Solutions:

1. **Use a VPS or Cloud Platform**:
   - Deploy to Heroku, Railway, Render, or DigitalOcean App Platform
   - These platforms support persistent background workers

2. **External Cron Service**:
   - Use services like Cron-Job.org, EasyCron, or GitHub Actions
   - Set up webhooks to trigger the scraper via HTTP requests

3. **If Cron is Available in cPanel**:
   - Some cPanel hosts provide cron job access
   - Set up a cron job to run the scraper periodically:
     ```
     */5 * * * * /usr/bin/python3 /path/to/your/project/manage.py scrape_periodically --interval=300
     ```
   - Note: Adjust the Python path and project path according to your hosting setup

4. **Webhook-Based Approach**:
   - Create a simple endpoint that triggers the scraper
   - Use external cron services to call this endpoint
   - Example: `https://yourdomain.com/api/trigger-scrape`

5. **Manual Execution**:
   - Run the scraper manually when needed via SSH or hosting control panel
   - Not ideal for automated updates but works for occasional use

#### Best Practice for cPanel:
Given the constraints, consider deploying the main API to cPanel and running the scraper on a separate platform that supports background processes.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests (if any)
5. Submit a pull request

## License

This project is licensed under the MIT License.