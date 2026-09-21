from django.contrib.sitemaps import Sitemap
from django.contrib.sites.models import Site
from django.core.paginator import Paginator
from django.urls import reverse

from .models import NewsArticle
from .views import NewsListView


class NewsArticleSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7
    i18n = True
    alternates = True
    x_default = True

    def items(self):
        return NewsArticle.objects.published(site=Site.objects.get_current()).filter(
            auth_required=False
        )

    def lastmod(self, obj):
        return obj.modified


class NewsListSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.6
    i18n = True
    alternates = True
    x_default = True

    def items(self):
        queryset = NewsArticle.objects.published(site=Site.objects.get_current()).filter(
            auth_required=False
        )
        return Paginator(queryset, NewsListView.paginate_by).page_range

    def location(self, page):
        return f"{reverse('news:list')}?page={page}"
