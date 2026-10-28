import html

from django.apps import apps
from django.conf import settings
from django.contrib.postgres.search import (
    SearchHeadline,
    SearchQuery,
    SearchRank,
    SearchVector,
)
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import F, Func, TextField
from django.db.models.constants import LOOKUP_SEP
from django.shortcuts import render
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import get_language
from editor_js.fields import EditorJSField

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


class EditorJsText(Func):
    """
    Plain text of an Editor.js document: the strings typed by the editors
    (text, captions, list items, table cells, code) in document order,
    without the JSON structure around them nor the inline markup.
    """

    output_field = TextField()
    # One set-returning function only: a lateral join between two of them
    # makes the planner estimate millions of rows per document, which turns
    # on the JIT compiler and adds a fixed ~100ms to every search query.
    # The path takes the text keys at any depth, plus the ``items`` of lists
    # saved in the older format, where they are bare strings; the items of
    # the newer format are objects, reached through their ``content`` key.
    # Descending at most two levels reaches the cells of a table.
    template = (
        "(SELECT regexp_replace(string_agg(value #>> '{}', ' ' ORDER BY ord), "
        "'<[^>]*>', ' ', 'g') "
        "FROM jsonb_path_query(%(expressions)s, "
        "'strict $.blocks[*].data.** ? (@.type() == \"object\").keyvalue() "
        "? (@.key == \"text\" || @.key == \"caption\" "
        "|| @.key == \"content\" || @.key == \"code\" "
        "|| (@.key == \"items\" "
        "&& !(exists (@.value[*] ? (@.type() == \"object\")))))"
        ".value.**{0 to 2} ? (@.type() == \"string\")', '{}', true) "
        "WITH ORDINALITY AS editor_js_text(value, ord))"
    )


def has_search_terms(query_text, pg_search_config):
    """
    Whether the query keeps any term once the configuration drops its stop
    words: "chi siamo" is made of Italian stop words only, and an empty query
    matches nothing.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT numnode(websearch_to_tsquery(%s::regconfig, %s))",
            [pg_search_config, query_text],
        )
        return cursor.fetchone()[0] > 0


def get_search_expression(model, field_path):
    """Return the expression indexed for a ``search_fields`` entry."""
    field = None
    for name in field_path.split(LOOKUP_SEP):
        field = model._meta.get_field(name)
        model = field.related_model or model
    if isinstance(field, EditorJSField):
        return EditorJsText(F(field_path))
    return F(field_path)


def repeats_title(headline, item):
    """
    Whether a headline only repeats text already shown as the title of the
    result, like the title itself or the first name of an expert.
    """
    text = headline.replace(HIGHLIGHT_START, "").replace(HIGHLIGHT_STOP, "")
    title = str(getattr(item, "title", None) or item)
    return text.strip().casefold() in title.casefold()


def render_search_headline(value):
    """Escape indexed content while preserving our controlled highlight tags."""
    # Editor.js text carries HTML entities (&nbsp;, &amp;...): decode them
    # before escaping, or they would be shown literally.
    escaped = str(escape(html.unescape(value or "")))
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
        if not has_search_terms(query_text, pg_search_config):
            # Search the words as they are, without stemming nor stop words.
            pg_search_config = "simple"
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
            search_expressions = {
                field: get_search_expression(model, field) for field in search_fields
            }
            search_vector = SearchVector(
                *search_expressions.values(), config=pg_search_config
            )

            headline_annotations = {
                f"headline_{field}": SearchHeadline(
                    search_expressions[field],
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
                headlines = [
                    headline
                    for field in search_fields
                    if (headline := getattr(item, f"headline_{field}"))
                    and not repeats_title(headline, item)
                ]
                best_headline = next(
                    (h for h in headlines if HIGHLIGHT_START in h),
                    headlines[0] if headlines else "",
                )

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
