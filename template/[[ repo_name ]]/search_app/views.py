from collections import defaultdict

from django.apps import apps
from django.conf import settings
from django.contrib.postgres.search import (
    SearchHeadline,
    SearchQuery,
    SearchRank,
    SearchVector,
)
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
    """
    Handles the search logic.
    - Finds all models that inherit from the `Searchable` abstract model.
    - Performs a full-text search across the specified fields of these models.
    - Dynamically generates a headline snippet from the specific field where
      the search term was found.
    - Aggregates and groups the results by model, then ranks them.
    """
    query_text = request.GET.get('q', '').strip()
    grouped_results = defaultdict(list)
    total_results_count = 0
    current_language = get_language() or settings.LANGUAGE_CODE
    pg_search_config = get_postgres_search_config(current_language)

    context = {
        'query': query_text,
        'grouped_results': {},
        'total_results_count': 0,
    }

    if query_text:
        search_query = SearchQuery(query_text, config=pg_search_config, search_type='websearch')
        all_models = apps.get_models()
        
        searchable_models = [
            model for model in all_models 
            if issubclass(model, Searchable) and not model._meta.abstract
        ]

        headline_options = {
            'start_sel': HIGHLIGHT_START,
            'stop_sel': HIGHLIGHT_STOP,
            'max_fragments': 3,
            'fragment_delimiter': ' ... '
        }

        for model in searchable_models:
            search_fields = model.get_search_fields()
            search_vector = SearchVector(*search_fields, config=pg_search_config)

            headline_annotations = {
                f'headline_{field}': SearchHeadline(field, search_query, config=pg_search_config, **headline_options)
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
                .order_by('id', '-rank')
                .distinct('id')
            )
            result_limit = max(1, int(settings.SEARCH_RESULTS_PER_MODEL))
            model_verbose_name_plural = model._meta.verbose_name_plural.title()
            for item in queryset[:result_limit]:
                best_headline = ''
                for field in search_fields:
                    headline_content = getattr(item, f'headline_{field}')
                    if headline_content and HIGHLIGHT_START in headline_content:
                        best_headline = headline_content
                        break

                if not best_headline:
                    for field in search_fields:
                        fallback_content = getattr(item, f'headline_{field}')
                        if fallback_content:
                            best_headline = fallback_content
                            break

                item.headline = render_search_headline(best_headline)
                grouped_results[model_verbose_name_plural].append(item)

        # Sort results within each group by rank and calculate total
        for model_name, results_list in grouped_results.items():
            results_list.sort(key=lambda r: r.rank, reverse=True)
            total_results_count += len(results_list)
            

        # Convert defaultdict to a regular dict for the template
        context['grouped_results'] = dict(grouped_results)
        context['total_results_count'] = total_results_count

    return render(request, 'search_app/search_results.html', context)
