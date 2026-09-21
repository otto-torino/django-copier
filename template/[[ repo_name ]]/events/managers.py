from django.contrib.sites.models import Site
from django.db import models
from django.utils import timezone


class EventQuerySet(models.QuerySet):
    def published(self, *, site=None):
        queryset = self.filter(status=self.model.PUBLISHED)
        if site is not None:
            queryset = queryset.filter(sites=site)
        return queryset

    def current(self):
        today = timezone.localdate()
        return self.filter(
            models.Q(date__gte=today) | models.Q(date_end__gte=today)
        )

    def upcoming(self, *, site=None):
        return self.published(site=site).current()

    def featured(self, *, site=None):
        return self.upcoming(site=site).filter(is_featured=True)

    def accessible_by(self, user, *, site=None):
        site = site or Site.objects.get_current()
        if user and user.has_perm("events.change_event"):
            return self.filter(sites=site)
        queryset = self.published(site=site)
        if not user or not user.is_authenticated:
            queryset = queryset.filter(auth_required=False)
        return queryset
