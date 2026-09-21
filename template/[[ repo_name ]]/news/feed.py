from datetime import datetime, time

from django.contrib.sites.models import Site
from django.contrib.syndication.views import Feed
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import NewsArticle


class NewsFeed(Feed):
    title = _("News")
    link = "/news/"
    description = _("Latest published news")

    def items(self):
        return NewsArticle.objects.published(site=Site.objects.get_current()).filter(
            auth_required=False
        )[:100]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.abstract or ""

    def item_pubdate(self, item):
        value = datetime.combine(item.publication_date, time.min)
        return timezone.make_aware(value)

    def item_updateddate(self, item):
        return item.modified
