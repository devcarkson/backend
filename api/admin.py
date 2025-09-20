from django.contrib import admin
from .models import Article


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'url', 'source', 'category', 'is_scraped', 'published_at', 'scraped_at')
    list_filter = ('is_scraped', 'category', 'source', 'published_at')
    search_fields = ('title', 'url', 'content')
    readonly_fields = ('scraped_at',)
    ordering = ('-published_at',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related()

    fieldsets = (
        ('Basic Information', {
            'fields': ('url', 'title', 'excerpt', 'content')
        }),
        ('Metadata', {
            'fields': ('author', 'published_at', 'source', 'category', 'read_time', 'image')
        }),
        ('Scraping Status', {
            'fields': ('is_scraped', 'scraped_at')
        }),
    )