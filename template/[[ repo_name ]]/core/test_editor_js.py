from django.test import SimpleTestCase, override_settings
from django.utils.translation import override

from .editor_js import SiteEditorJsRenderer


class EditorEmbedTests(SimpleTestCase):
    """The embeds of the editor wait for the cookie consent, like the video blocks."""

    YOUTUBE = {
        "service": "youtube",
        "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "embed": "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "caption": "The video",
    }
    INSTAGRAM = {
        "service": "instagram",
        "source": "https://www.instagram.com/p/abc/",
        "embed": "https://www.instagram.com/p/abc/embed",
        "caption": "",
    }

    def render(self, data):
        with override("en"):
            return SiteEditorJsRenderer({"blocks": []}).render_embed(data)

    def test_without_the_cookie_banner_the_embed_plays_at_once(self):
        html = self.render(self.YOUTUBE)

        self.assertIn('src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"', html)
        self.assertNotIn("data-player-consent", html)
        self.assertIn("<figcaption>The video</figcaption>", html)

    @override_settings(COOKIERULEZ_WIDGET_CODE="widget")
    def test_with_the_cookie_banner_the_embed_waits_and_explains_why(self):
        html = self.render(self.YOUTUBE)

        self.assertIn(
            'data-src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ" data-cookierulez="marketing"', html
        )
        self.assertNotIn(' src="', html)
        self.assertIn("The YouTube player is not displayed", html)
        self.assertIn('href="https://www.youtube.com/watch?v=dQw4w9WgXcQ"', html)
        self.assertIn(">Watch on YouTube</a>", html)

    @override_settings(COOKIERULEZ_WIDGET_CODE="widget")
    def test_an_embed_that_is_not_a_player_speaks_of_content(self):
        html = self.render(self.INSTAGRAM)

        self.assertIn("The Instagram content is not displayed", html)
        self.assertIn(">Open on Instagram</a>", html)

    def test_an_embed_without_address_renders_nothing(self):
        self.assertEqual(self.render({"service": "youtube", "embed": ""}), "")
