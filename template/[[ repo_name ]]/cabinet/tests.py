from django.test import TestCase
from django.urls import reverse


class PermalinkTests(TestCase):
    def test_permalink_has_no_language_prefix(self):
        self.assertEqual(
            reverse("cabinet:permalink", args=[1]), "/cabinet/permalink/1/"
        )

    def test_permalink_of_a_missing_file_is_not_found(self):
        response = self.client.get("/cabinet/permalink/1/")

        self.assertEqual(response.status_code, 404)
