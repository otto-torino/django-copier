import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.test import Client, TestCase
from django.urls import reverse

import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from .models import Page, PageContentCard, PageContentCards, PageContentText


class SaveContentPositionTests(TestCase):
    csrf_token = "a" * 32

    def setUp(self):
        site = Site.objects.get_current()
        self.page = self.create_page("/page/")
        self.page.sites.add(site)
        self.other_page = self.create_page("/other/")
        self.other_page.sites.add(site)
        content_type = ContentType.objects.get_for_model(PageContentText)
        self.first = PageContentText.objects.create(
            page=self.page,
            content_type=content_type,
            name="First",
            position=0,
        )
        self.second = PageContentText.objects.create(
            page=self.page,
            content_type=content_type,
            name="Second",
            position=1,
        )
        self.other = PageContentText.objects.create(
            page=self.other_page,
            content_type=content_type,
            name="Other",
            position=0,
        )
        self.user = get_user_model().objects.create_superuser(
            username="admin",
            password="password",
            email="admin@example.com",
        )
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def create_page(self, url):
        return Page.objects.create(
            url=url,
            title=url.strip("/").title(),
            status=Page.PUBLISHED,
        )

    def save_url(self, page=None):
        return reverse(
            "admin:pages_page_save_position",
            args=[(page or self.page).pk],
        )

    def post_order(self, order, *, include_csrf=True, page=None):
        headers = {}
        if include_csrf:
            self.client.cookies["csrftoken"] = self.csrf_token
            headers["HTTP_X_CSRFTOKEN"] = self.csrf_token
        return self.client.post(
            self.save_url(page),
            data=json.dumps({"order": order}),
            content_type="application/json",
            **headers,
        )

    def test_request_without_csrf_token_is_rejected(self):
        response = self.post_order([], include_csrf=False)

        self.assertEqual(response.status_code, 403)

    def test_valid_request_saves_normalized_order(self):
        response = self.post_order(
            [
                {"id": str(self.second.pk), "position": 99},
                {"id": str(self.first.pk), "position": -10},
            ]
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"saved": True})
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.second.position, 0)
        self.assertEqual(self.first.position, 1)

    def test_content_blocks_from_another_page_are_rejected(self):
        response = self.post_order([{"id": self.other.pk}])

        self.assertEqual(response.status_code, 400)
        self.assertIn("does not belong", response.json()["error"])

    def test_duplicate_and_malformed_ids_are_rejected(self):
        invalid_orders = (
            [{"id": self.first.pk}, {"id": self.first.pk}],
            [{"id": "not-an-id"}],
            [None],
        )

        for order in invalid_orders:
            with self.subTest(order=order):
                response = self.post_order(order)
                self.assertEqual(response.status_code, 400)

    def test_endpoint_accepts_post_only(self):
        response = self.client.get(self.save_url())

        self.assertEqual(response.status_code, 405)


class EditContentsTests(TestCase):
    def setUp(self):
        self.page = Page.objects.create(url="/page/", title="Page", status=Page.PUBLISHED)
        content_type = ContentType.objects.get_for_model(PageContentText)
        for position, (name, enabled, layout_content) in enumerate(
            (
                ("Enabled block", True, False),
                ("Disabled block", False, False),
                ("Disabled layout block", False, True),
            )
        ):
            block = PageContentText.objects.create(
                page=self.page,
                content_type=content_type,
                name=name,
                enabled=enabled,
                layout_content=layout_content,
                position=position,
            )
            # the admin stores the id to find the specific block from the base one
            block.object_id = block.pk
            block.save()
        self.client.force_login(
            get_user_model().objects.create_superuser(
                username="admin",
                password="password",
                email="admin@example.com",
            )
        )

    def test_disabled_blocks_are_listed_as_hidden(self):
        response = self.client.get(
            reverse("admin:pages_page_edit_content", kwargs={"id": self.page.pk})
        )

        self.assertContains(response, "Enabled block")
        self.assertContains(response, "Disabled block")
        self.assertContains(response, "Disabled layout block")
        self.assertContains(response, "content-block is-disabled", count=2)
        self.assertContains(response, 'role="switch"', count=3)
        # only the blocks shown on their own can be dragged
        self.assertContains(response, "content-block-drag-handle", count=2)

    def test_a_block_is_listed_with_its_icon_and_a_summary(self):
        block = PageContentText.objects.get(name="Enabled block")
        block.content = {"blocks": [{"type": "paragraph", "data": {"text": "La <b>prima</b> riga"}}]}
        block.save()

        response = self.client.get(
            reverse("admin:pages_page_edit_content", kwargs={"id": self.page.pk})
        )

        self.assertContains(response, '<i class="material-symbols-outlined">notes</i>')
        self.assertContains(response, '<span class="content-block-summary">La prima riga</span>')



class BlockActionsTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.page = Page.objects.create(url="/page/", title="Page", status=Page.PUBLISHED)
        self.other_page = Page.objects.create(url="/other/", title="Other", status=Page.PUBLISHED)
        self.text = self.add(PageContentText, name="Intro", position=0)
        self.cards = self.add(PageContentCards, name="Persone", position=1, columns=1)
        self.last = self.add(PageContentText, name="Fine", position=2)
        content = BytesIO()
        Image.new("RGB", (20, 20), "red").save(content, "PNG")
        PageContentCard.objects.create(
            block=self.cards,
            image=SimpleUploadedFile("foto.png", content.getvalue(), content_type="image/png"),
            text={"blocks": [{"type": "paragraph", "data": {"text": "Alice"}}]},
        )
        self.client.force_login(
            get_user_model().objects.create_superuser("admin", "admin@example.com", "password")
        )

    def add(self, model, page=None, **values):
        block = model.objects.create(
            page=page or self.page, content_type=ContentType.objects.get_for_model(model), **values
        )
        block.object_id = block.pk
        block.save()
        return block

    def url(self, action, block, page=None):
        return reverse(f"admin:pages_page_{action}_block", args=[(page or self.page).pk, block.pk])

    def test_the_switch_hides_and_shows_a_block(self):
        response = self.client.post(self.url("toggle", self.text))

        self.assertEqual(response.json(), {"enabled": False})
        self.text.refresh_from_db()
        self.assertFalse(self.text.enabled)
        self.assertEqual(self.client.post(self.url("toggle", self.text)).json(), {"enabled": True})

    def test_the_actions_take_only_the_blocks_of_the_page(self):
        other = self.add(PageContentText, page=self.other_page, name="Altrove", position=0)

        for action in ("toggle", "duplicate"):
            with self.subTest(action=action):
                self.assertEqual(self.client.post(self.url(action, other)).status_code, 404)
        self.assertEqual(self.client.get(self.url("toggle", self.text)).status_code, 405)

    def test_a_copy_comes_right_after_the_block_with_its_items_and_files(self):
        response = self.client.post(self.url("duplicate", self.cards))

        copy = PageContentCards.objects.exclude(pk=self.cards.pk).get()
        self.assertRedirects(
            response,
            reverse("admin:pages_page_edit_content", kwargs={"id": self.page.pk}) + f"#block-row-{copy.pk}",
            fetch_redirect_response=False,
        )
        self.assertTrue(copy.name.startswith("Persone (") and copy.name != "Persone")
        self.assertEqual(copy.object_id, copy.pk)
        self.assertEqual((copy.columns, copy.page_id), (1, self.page.pk))
        self.assertEqual(
            list(self.page.content_blocks.order_by("position").values_list("name", flat=True)),
            ["Intro", "Persone", copy.name, "Fine"],
        )
        original_card, copied_card = self.cards.cards.get(), copy.cards.get()
        self.assertEqual(str(copied_card), "Alice")
        self.assertNotEqual(copied_card.image.name, original_card.image.name)
        self.assertTrue(copied_card.image.storage.exists(copied_card.image.name))


class AddBlockTests(TestCase):
    def setUp(self):
        self.page = Page.objects.create(url="/page/", title="Page", status=Page.PUBLISHED)
        self.first = self.add("Primo", 0)
        self.second = self.add("Secondo", 1)
        self.client.force_login(
            get_user_model().objects.create_superuser("admin", "admin@example.com", "password")
        )

    def add(self, name, position, **values):
        block = PageContentText.objects.create(
            page=self.page,
            content_type=ContentType.objects.get_for_model(PageContentText),
            name=name,
            position=position,
            **values,
        )
        block.object_id = block.pk
        block.save()
        return block

    def post_text(self, name, after=None):
        url = f"{reverse('admin:pages_pagecontenttext_add')}?page={self.page.pk}"
        if after is not None:
            url += f"&after={after}"
        # the name of the default language with modeltranslation
        field = "name"
        if "modeltranslation" in settings.INSTALLED_APPS:
            field = f"name_{getattr(settings, 'MODELTRANSLATION_DEFAULT_LANGUAGE', settings.LANGUAGE_CODE)}"
        return self.client.post(url, {field: name, "enabled": "on"})

    def names(self):
        return list(self.page.content_blocks.order_by("position").values_list("name", flat=True))

    def test_a_new_block_goes_at_the_end_on_its_row(self):
        response = self.post_text("Nuovo")

        new = PageContentText.objects.get(name="Nuovo")
        self.assertRedirects(
            response,
            reverse("admin:pages_page_edit_content", kwargs={"id": self.page.pk}) + f"#block-row-{new.pk}",
            fetch_redirect_response=False,
        )
        self.assertEqual(self.names(), ["Primo", "Secondo", "Nuovo"])

    def test_a_new_block_goes_after_the_chosen_one_or_at_the_beginning(self):
        self.post_text("Dopo il primo", after=self.first.pk)
        self.post_text("In cima", after="start")

        self.assertEqual(self.names(), ["In cima", "Primo", "Dopo il primo", "Secondo"])

    def test_the_end_is_after_the_last_position_not_the_number_of_blocks(self):
        # a block deleted between the others leaves a gap: the count would give a duplicate
        self.second.position = 5
        self.second.save()

        self.post_text("Nuovo")

        self.assertEqual(PageContentText.objects.get(name="Nuovo").position, 6)

    def test_the_blocks_for_the_columns_are_listed_only_when_there_are_some(self):
        url = reverse("admin:pages_page_edit_content", kwargs={"id": self.page.pk})

        self.assertNotContains(self.client.get(url), 'id="layout-blocks-list"')

        self.add("Per le colonne", 2, layout_content=True)
        response = self.client.get(url)

        self.assertContains(response, 'id="layout-blocks-list"')
        self.assertContains(response, "content-block-badge content-block-off")
        self.assertContains(response, reverse("admin:pages_page_change", args=[self.page.pk]))
        self.assertContains(response, f'href="{self.page.get_absolute_url()}"')
