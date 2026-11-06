import json
import tempfile
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.utils import flatten_fieldsets
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.db.models import ImageField
from django.urls import reverse
from django.utils.translation import override
from PIL import Image

from pages.models import PageContentImage, PageContentMultiImageItem, PageContentTextImage

from .models import Preferences


class AdminImageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser("admin", "admin@example.com", "x")

    def setUp(self):
        media_root = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(override_settings(MEDIA_ROOT=media_root))
        Image.new("RGB", (800, 400), "navy").save(Path(media_root) / "sample.png")

    def test_every_image_has_a_large_preview_subject_picker_and_valid_alt_target(self):
        for model in apps.get_models():
            if model._meta.proxy:
                continue
            for field in model._meta.fields:
                if not isinstance(field, ImageField):
                    continue
                with self.subTest(model=model._meta.label, field=field.name):
                    instance = model(**{field.name: "sample.png"})
                    location = field.subject_location_field
                    self.assertTrue(location)
                    self.assertEqual(getattr(instance, location), "50,50")
                    self.assertTrue(field.alt_field)
                    model._meta.get_field(field.alt_field)
                    html = field.formfield().widget.render(field.name, getattr(instance, field.name))
                    self.assertIn('data-baton-subject-preview', html)
                    self.assertIn(f'data-subject-location-field="{location}"', html)
                    self.assertIn('width: 400px', html)
                    self.assertIn(f'alt_field="{field.alt_field}"', html)

    def test_admin_forms_and_inlines_include_the_coordinates_and_alt_target(self):
        request = RequestFactory().get("/admin/")
        request.user = self.user
        for model, model_admin in admin.site._registry.items():
            images = [field for field in model._meta.fields if isinstance(field, ImageField)]
            instance = model(**{field.name: "sample.png" for field in images}) if images else None
            if images:
                form = model_admin.get_form(request, instance)
                displayed = flatten_fieldsets(model_admin.get_fieldsets(request, instance))
                for field in images:
                    with self.subTest(model=model._meta.label, field=field.name):
                        self.assertIn(field.name, form.base_fields)
                        self.assertIn(field.subject_location_field, form.base_fields)
                        self.assertIn(field.subject_location_field, displayed)
                        self.assertIn(field.alt_field, form.base_fields)
            for inline_class in model_admin.inlines:
                fields = [field for field in inline_class.model._meta.fields if isinstance(field, ImageField)]
                if not fields:
                    continue
                inline = inline_class(model, admin.site)
                form = inline.get_formset(request, instance).form
                for field in fields:
                    with self.subTest(inline=inline_class.__name__, field=field.name):
                        self.assertIn(field.subject_location_field, form.base_fields)
                        self.assertIn(field.alt_field, form.base_fields)

    def test_preferences_save_the_subject_and_alt_without_requiring_an_image(self):
        self.client.force_login(self.user)
        pref = Preferences.instance()
        translated = "modeltranslation" in settings.INSTALLED_APPS
        suffix = "_" + settings.LANGUAGE_CODE.replace("-", "_") if translated else ""
        payload = {
            "site_title" + suffix: "Example site",
            "ai_models": json.dumps(pref.ai_models),
            "meta_image_subject_location": "25,75",
            "meta_image_alt_text" + suffix: "Accessible site image",
        }

        response = self.client.post(reverse("admin:core_preferences_change", args=[pref.pk]), payload)

        self.assertEqual(response.status_code, 302)
        pref.refresh_from_db()
        self.assertEqual(pref.meta_image_subject_location, "25,75")
        self.assertEqual(pref.meta_image_alt_text, "Accessible site image")

    def test_block_alts_are_separate_from_captions_and_keep_the_caption_fallback(self):
        cases = (
            (PageContentImage, "image", "pages/page_content_image.html", "obj"),
            (PageContentTextImage, "image", "pages/includes/textimage_body.html", "obj"),
            (PageContentMultiImageItem, "file", "pages/grid/grid_item.html", "image"),
        )
        for model, field, template, variable in cases:
            with self.subTest(model=model.__name__):
                block = model(**{
                    field: "sample.png", "alt_text": "Accessible description",
                    "caption": "Visible caption",
                })
                context = {variable: block}
                html = render_to_string(template, context)
                self.assertIn('src="/media/sample.png"', html)
                self.assertIn('alt="Accessible description"', html)
                block.alt_text = ""
                self.assertIn('alt="Visible caption"', render_to_string(template, context))

    def test_meta_alt_uses_the_current_language_and_is_escaped(self):
        pref = Preferences(meta_image="sample.png")
        translated = "modeltranslation" in settings.INSTALLED_APPS
        for index, (language, _label) in enumerate(settings.LANGUAGES):
            field = "meta_image_alt_text_" + language.replace("-", "_") if translated else "meta_image_alt_text"
            setattr(pref, field, f'Image "{index}"')
        for index, (language, _label) in enumerate(settings.LANGUAGES):
            with self.subTest(language=language), override(language):
                html = render_to_string("base.html", {"pref": pref})
                self.assertIn(f'property="og:image:alt" content="Image &quot;{index}&quot;"', html)
                self.assertIn(f'name="twitter:image:alt" content="Image &quot;{index}&quot;"', html)
