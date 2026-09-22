from dataclasses import dataclass
from datetime import date, datetime

from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Count, Q

from .models import Searchable


@dataclass(frozen=True)
class RelatedContentItem:
    """A single suggestion rendered by the related content widget."""

    kind: str
    kind_label: str
    title: str
    url: str
    score: int
    date: date | datetime | None = None
    image_url: str = ""


def _searchable_models_with_tags():
    """Yield the concrete ``Searchable`` models that can be tag matched."""
    for model in apps.get_models():
        if model._meta.abstract or not issubclass(model, Searchable):
            continue
        try:
            model._meta.get_field("tags")
        except FieldDoesNotExist:
            continue
        yield model


def _item_date(instance):
    for field_name in ("publication_date", "date", "modified", "created"):
        value = getattr(instance, field_name, None)
        if value:
            return value
    return None


def _date_key(value):
    if value is None:
        return (0, 0, 0, 0, 0, 0)
    return (
        value.year,
        value.month,
        value.day,
        getattr(value, "hour", 0),
        getattr(value, "minute", 0),
        getattr(value, "second", 0),
    )


def _image_url(instance):
    image = getattr(instance, "image", None)
    if not image:
        return ""
    try:
        return image.url
    except (ValueError, AttributeError):
        return ""


def get_related_content(instance, request, *, limit=None):
    """
    Return accessible content sharing the greatest number of tags.

    Candidates are collected from every concrete ``Searchable`` model owning a
    ``tags`` field, through ``get_search_queryset(request)`` so that the access
    policy of each model is honoured, and ranked by the number of tags shared
    with ``instance``, then by date. The instance itself is never suggested.
    """
    if limit is None:
        limit = settings.RELATED_CONTENT_RESULTS
    limit = int(limit)
    tag_ids = list(instance.tags.values_list("pk", flat=True))
    if not tag_ids or limit < 1:
        return []

    candidates = []
    for model in _searchable_models_with_tags():
        queryset = model.get_search_queryset(request).filter(tags__in=tag_ids)
        if model is instance.__class__:
            queryset = queryset.exclude(pk=instance.pk)
        queryset = (
            queryset.annotate(
                related_score=Count(
                    "tags",
                    filter=Q(tags__in=tag_ids),
                    distinct=True,
                )
            )
            .order_by("-related_score", "pk")
            .distinct()
        )
        for related in queryset[:limit]:
            candidates.append(
                RelatedContentItem(
                    kind=related._meta.model_name,
                    kind_label=str(related._meta.verbose_name),
                    title=getattr(related, "title", "") or str(related),
                    url=related.get_absolute_url(),
                    score=related.related_score,
                    date=_item_date(related),
                    image_url=_image_url(related),
                )
            )

    candidates.sort(
        key=lambda item: (item.score, _date_key(item.date)),
        reverse=True,
    )
    return candidates[:limit]
