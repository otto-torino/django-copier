from django.contrib.sites.models import Site
from django.contrib.syndication.views import Feed
from django.utils.translation import gettext_lazy as _

from .models import Event


class EventsFeed(Feed):
    title = _("Events")
    link = "/events/"
    description = _("Upcoming events")

    def items(self):
        return Event.objects.upcoming(site=Site.objects.get_current()).filter(
            auth_required=False
        )[:100]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.abstract or ""

    def item_pubdate(self, item):
        return item.created

    def item_updateddate(self, item):
        return item.modified
