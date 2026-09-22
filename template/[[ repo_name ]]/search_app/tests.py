from django.contrib.auth.models import AnonymousUser
from django.contrib.sites.models import Site
from django.core.exceptions import ImproperlyConfigured
from django.template import Context, Template
from django.test import (
    RequestFactory,
    SimpleTestCase,
    TestCase,
    override_settings,
)
from django.urls import reverse
from django.utils.translation import override

from pages.models import Page
from tagall.models import Tag

from .models import Searchable
from .related import get_related_content
from .views import (
    HIGHLIGHT_START,
    HIGHLIGHT_STOP,
    get_postgres_search_config,
    render_search_headline,
)


class SearchableTests(SimpleTestCase):
    def test_relevance_defaults_to_medium(self):
        field = Searchable._meta.get_field("relevance")

        self.assertEqual(field.max_length, 10)
        self.assertEqual(field.default, Searchable.RelevanceChoices.MEDIUM)
        self.assertEqual(
            dict(field.choices),
            {"high": "high", "medium": "medium", "low": "low"},
        )

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


class RelatedContentTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get_current()
        self.site.domain = "testserver"
        self.site.save()
        Site.objects.clear_cache()
        self.request = RequestFactory().get("/")
        self.request.user = AnonymousUser()

    def _create_page(self, url, title, tags, **kwargs):
        kwargs.setdefault("status", Page.PUBLISHED)
        page = Page.objects.create(
            url=url,
            title=title,
            **kwargs,
        )
        page.sites.add(self.site)
        page.tags.set(tags)
        return page

    def test_related_content_ranks_the_most_shared_tags_first(self):
        first_tag = Tag.objects.create(name="Security")
        second_tag = Tag.objects.create(name="Privacy")
        source = self._create_page(
            "/source/", "Source page", [first_tag, second_tag]
        )
        self._create_page("/closest/", "Closest page", [first_tag, second_tag])
        self._create_page("/loosest/", "Loosest page", [first_tag])
        self._create_page("/unrelated/", "Unrelated page", [])

        results = get_related_content(source, self.request)

        self.assertEqual(
            [item.title for item in results],
            ["Closest page", "Loosest page"],
        )
        self.assertEqual([item.shared_tags for item in results], [2, 1])
        self.assertEqual([item.score for item in results], [8, 5])
        self.assertEqual(results[0].kind, "page")
        self.assertEqual(
            results[0].url,
            Page.objects.get(url="/closest/").get_absolute_url(),
        )

    def test_related_content_uses_relevance_to_break_tag_ties(self):
        tag = Tag.objects.create(name="Security")
        source = self._create_page("/source/", "Source page", [tag])
        self._create_page(
            "/low/",
            "Low relevance",
            [tag],
            relevance=Searchable.RelevanceChoices.LOW,
        )
        self._create_page(
            "/high/",
            "High relevance",
            [tag],
            relevance=Searchable.RelevanceChoices.HIGH,
        )

        results = get_related_content(source, self.request)

        self.assertEqual(
            [item.title for item in results],
            ["High relevance", "Low relevance"],
        )
        self.assertEqual([item.score for item in results], [6, 4])

    def test_related_content_hides_items_the_request_cannot_discover(self):
        tag = Tag.objects.create(name="Security")
        source = self._create_page("/source/", "Source page", [tag])
        self._create_page(
            "/restricted/",
            "Restricted page",
            [tag],
            registration_required=True,
        )
        self._create_page("/draft/", "Draft page", [tag], status=Page.DRAFT)

        titles = [
            item.title for item in get_related_content(source, self.request)
        ]

        self.assertEqual(titles, [])

    def test_related_content_is_empty_without_tags(self):
        source = self._create_page("/source/", "Source page", [])
        tag = Tag.objects.create(name="Security")
        self._create_page("/tagged/", "Tagged page", [tag])

        self.assertEqual(get_related_content(source, self.request), [])

    @override_settings(RELATED_CONTENT_RESULTS=1)
    def test_related_content_honours_the_configured_limit(self):
        tag = Tag.objects.create(name="Security")
        source = self._create_page("/source/", "Source page", [tag])
        self._create_page("/first/", "First page", [tag])
        self._create_page("/second/", "Second page", [tag])

        self.assertEqual(len(get_related_content(source, self.request)), 1)

    def test_widget_renders_escaped_suggestions(self):
        tag = Tag.objects.create(name="Security")
        source = self._create_page("/source/", "Source page", [tag])
        related = self._create_page(
            "/related/", "<b>Related</b> page", [tag]
        )

        rendered = Template(
            "{% load search_tags %}{% related_content_widget results %}"
        ).render(
            Context(
                {"results": get_related_content(source, self.request)}
            )
        )

        self.assertIn(f'href="{related.get_absolute_url()}"', rendered)
        self.assertIn("&lt;b&gt;Related&lt;/b&gt; page", rendered)
        self.assertNotIn("<b>Related</b>", rendered)

    def test_widget_renders_nothing_without_suggestions(self):
        rendered = Template(
            "{% load search_tags %}{% related_content_widget results %}"
        ).render(Context({"results": []}))

        self.assertNotIn("data-related-content", rendered)
