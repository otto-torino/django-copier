from django.contrib.sites.models import Site
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils.translation import override

from pages.models import Page

from .models import Searchable
from .views import (
    HIGHLIGHT_START,
    HIGHLIGHT_STOP,
    get_postgres_search_config,
    render_search_headline,
)


class SearchableTests(SimpleTestCase):
    def test_search_queryset_must_be_defined_explicitly(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured,
            "Searchable must define a get_search_queryset(request) method.",
        ):
            Searchable.get_search_queryset(request=None)


class SearchSafetyTests(SimpleTestCase):
    def test_language_codes_map_to_postgres_configurations(self):
        self.assertEqual(get_postgres_search_config("it"), "italian")
        self.assertEqual(get_postgres_search_config("en-us"), "english")
        self.assertEqual(get_postgres_search_config("fr_FR"), "french")
        self.assertEqual(get_postgres_search_config("unknown"), "simple")

    def test_headline_escapes_content_and_preserves_only_controlled_markup(self):
        headline = render_search_headline(
            HIGHLIGHT_START
            + '<script>alert("xss")</script>'
            + HIGHLIGHT_STOP
        )

        self.assertIn('<span class="bg-yellow-200 font-bold">', headline)
        self.assertIn("&lt;script&gt;", headline)
        self.assertNotIn("<script>", headline)


class SearchViewTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get_current()
        self.site.domain = "testserver"
        self.site.save()
        Site.objects.clear_cache()
        self.page = Page.objects.create(
            url="/searchable/",
            title="Searchable needle",
            status=Page.PUBLISHED,
        )
        self.page.sites.add(self.site)

    def test_search_executes_with_the_active_language(self):
        with override("it"):
            response = self.client.get(
                reverse("search_app:search"),
                {"q": "needle"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Searchable needle")

    @override_settings(SEARCH_RESULTS_PER_MODEL=10, SEARCH_RESULTS_PER_PAGE=2)
    def test_search_results_are_paginated_and_keep_the_query(self):
        for index in range(3):
            page = Page.objects.create(
                url=f"/searchable-{index}/",
                title=f"Searchable needle {index}",
                status=Page.PUBLISHED,
            )
            page.sites.add(self.site)

        response = self.client.get(
            reverse("search_app:search"),
            {"q": "needle", "page": 2},
        )

        self.assertEqual(response.status_code, 200)
        page_obj = response.context["page_obj"]
        self.assertEqual(page_obj.number, 2)
        self.assertEqual(page_obj.paginator.count, 4)
        self.assertEqual(len(page_obj.object_list), 2)
        self.assertContains(response, "?q=needle&amp;page=1")

    @override_settings(SEARCH_RESULTS_PER_MODEL=2, SEARCH_RESULTS_PER_PAGE=10)
    def test_search_limits_results_per_model(self):
        for index in range(3):
            page = Page.objects.create(
                url=f"/limited-{index}/",
                title=f"Limited needle {index}",
                status=Page.PUBLISHED,
            )
            page.sites.add(self.site)

        response = self.client.get(
            reverse("search_app:search"),
            {"q": "needle"},
        )

        self.assertEqual(response.context["total_results_count"], 2)
        self.assertIs(response.context["results_truncated"], True)
        self.assertContains(response, "Showing the first 2 results")
