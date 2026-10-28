from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import translation


@skipUnless("it" in dict(settings.LANGUAGES), "Italian is not enabled")
class AdminJavaScriptCatalogTests(TestCase):
    def test_selector_widget_strings_are_translated(self):
        self.client.force_login(
            get_user_model().objects.create_superuser(
                username="admin",
                password="password",
                email="admin@example.com",
            )
        )
        with translation.override("it"):
            url = reverse("admin:jsi18n")

        response = self.client.get(url, headers={"accept-language": "it"})

        self.assertContains(response, "Scegli tutto")
