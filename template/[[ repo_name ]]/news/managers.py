from django.contrib.sites.models import Site
from django.db import models
from django.utils import timezone


class NewsArticleQuerySet(models.QuerySet):
    def published(self, *, site=None):
        queryset = self.filter(
            status=self.model.PUBLISHED,
            publication_date__lte=timezone.localdate(),
        )
        if site is not None:
            queryset = queryset.filter(sites=site)
        return queryset

    def featured(self, *, site=None):
        return self.published(site=site).filter(is_featured=True)

    def accessible_by(self, user, *, site=None):
        site = site or Site.objects.get_current()
        if user and user.has_perm("news.change_newsarticle"):
            return self.filter(sites=site)
        queryset = self.published(site=site)
        if not user or not user.is_authenticated:
            queryset = queryset.filter(auth_required=False)
        return queryset
