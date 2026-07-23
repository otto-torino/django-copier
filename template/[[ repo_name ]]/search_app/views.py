from django.apps import apps
from django.conf import settings
from django.contrib.postgres.search import (
    SearchHeadline,
    SearchQuery,
    SearchRank,
    SearchVector,
)
from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import get_language

from .models import Searchable


POSTGRES_SEARCH_CONFIGS = {
    "ar": "arabic",
    "da": "danish",
    "nl": "dutch",
    "en": "english",
    "fi": "finnish",
    "fr": "french",
    "de": "german",
    "hu": "hungarian",
    "it": "italian",
    "no": "norwegian",
    "pt": "portuguese",
    "ro": "romanian",
    "ru": "russian",
    "es": "spanish",
    "sv": "swedish",
    "tr": "turkish",
}
HIGHLIGHT_START = "__DJANGO_COPIER_HIGHLIGHT_START__"
HIGHLIGHT_STOP = "__DJANGO_COPIER_HIGHLIGHT_STOP__"
HIGHLIGHT_START_HTML = '<span class="bg-yellow-200 font-bold">'
HIGHLIGHT_STOP_HTML = "</span>"


def get_postgres_search_config(language_code):
    """Map a Django language code to a PostgreSQL text-search configuration."""
    normalized = (language_code or "").lower().replace("_", "-")
    return POSTGRES_SEARCH_CONFIGS.get(
        normalized,
        POSTGRES_SEARCH_CONFIGS.get(normalized.split("-", 1)[0], "simple"),
    )


def render_search_headline(value):
    """Escape indexed content while preserving our controlled highlight tags."""
    escaped = str(escape(value or ""))
    return mark_safe(
        escaped.replace(HIGHLIGHT_START, HIGHLIGHT_START_HTML).replace(
            HIGHLIGHT_STOP,
            HIGHLIGHT_STOP_HTML,
        )
    )


def search_view(request):
    """Search all concrete ``Searchable`` models and paginate ranked results."""
    query_text = request.GET.get("q", "").strip()
    current_language = get_language() or settings.LANGUAGE_CODE
    pg_search_config = get_postgres_search_config(current_language)

    context = {
        "query": query_text,
        "grouped_results": {},
        "page_obj": None,
        "results_truncated": False,
        "total_results_count": 0,
    }

    if query_text:
        search_query = SearchQuery(
            query_text,
            config=pg_search_config,
            search_type="websearch",
        )
        searchable_models = [
            model
            for model in apps.get_models()
            if issubclass(model, Searchable) and not model._meta.abstract
        ]

        headline_options = {
            "start_sel": HIGHLIGHT_START,
            "stop_sel": HIGHLIGHT_STOP,
            "max_fragments": 3,
            "fragment_delimiter": " ... ",
        }
        ranked_results = []
        result_limit = max(1, int(settings.SEARCH_RESULTS_PER_MODEL))
        results_truncated = False

        for model in searchable_models:
            search_fields = model.get_search_fields()
            search_vector = SearchVector(*search_fields, config=pg_search_config)

            headline_annotations = {
                f"headline_{field}": SearchHeadline(
                    field,
                    search_query,
                    config=pg_search_config,
                    **headline_options,
                )
                for field in search_fields
            }

            queryset = (
                model.get_search_queryset(request)
                .annotate(
                    search=search_vector,
                    rank=SearchRank(search_vector, search_query),
                    **headline_annotations,
                )
                .filter(search=search_query)
                .order_by("id", "-rank")
                .distinct("id")
            )
            model_verbose_name_plural = model._meta.verbose_name_plural.title()
            model_results = list(queryset[: result_limit + 1])
            if len(model_results) > result_limit:
                results_truncated = True
            for item in model_results[:result_limit]:
                best_headline = ""
                for field in search_fields:
                    headline_content = getattr(item, f"headline_{field}")
                    if headline_content and HIGHLIGHT_START in headline_content:
                        best_headline = headline_content
                        break

                if not best_headline:
                    for field in search_fields:
                        fallback_content = getattr(item, f"headline_{field}")
                        if fallback_content:
                            best_headline = fallback_content
                            break

                item.headline = render_search_headline(best_headline)
                ranked_results.append((model_verbose_name_plural, item))

        ranked_results.sort(key=lambda result: result[1].rank, reverse=True)
        page_size = max(1, int(settings.SEARCH_RESULTS_PER_PAGE))
        page_obj = Paginator(ranked_results, page_size).get_page(
            request.GET.get("page")
        )
        grouped_results = {}
        for model_name, item in page_obj.object_list:
            grouped_results.setdefault(model_name, []).append(item)

        context["grouped_results"] = grouped_results
        context["page_obj"] = page_obj
        context["results_truncated"] = results_truncated
        context["total_results_count"] = page_obj.paginator.count

    return render(request, "search_app/search_results.html", context)
