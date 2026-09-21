from django.contrib.sitemaps import Sitemap
from django.contrib.sites.models import Site
from django.core.paginator import Paginator
from django.urls import reverse

from .models import Event
from .views import EventListView


class EventSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7
    i18n = True
    alternates = True
    x_default = True

    def items(self):
        return Event.objects.published(site=Site.objects.get_current()).filter(
            auth_required=False
        )

    def lastmod(self, obj):
        return obj.modified


class EventListSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.6
    i18n = True
    alternates = True
    x_default = True

    def items(self):
        queryset = Event.objects.upcoming(site=Site.objects.get_current()).filter(
            auth_required=False
        )
        return Paginator(queryset, EventListView.paginate_by).page_range

    def location(self, page):
        return f"{reverse('events:list')}?page={page}"
