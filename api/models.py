from django.db import models
from django.utils import timezone


class Article(models.Model):
    url = models.URLField(unique=True)
    title = models.CharField(max_length=500, blank=True)
    content = models.TextField(blank=True)
    excerpt = models.TextField(blank=True)
    author = models.CharField(max_length=200, blank=True, null=True)
    published_at = models.DateTimeField(null=True, blank=True)
    scraped_at = models.DateTimeField(auto_now=True)
    source = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=100, blank=True)
    read_time = models.CharField(max_length=50, blank=True)
    image = models.URLField(blank=True)
    is_scraped = models.BooleanField(default=False)

    class Meta:
        ordering = ['-published_at']

    def __str__(self):
        return self.title or self.url