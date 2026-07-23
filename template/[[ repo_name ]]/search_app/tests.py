from django.contrib.sites.models import Site
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase
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
