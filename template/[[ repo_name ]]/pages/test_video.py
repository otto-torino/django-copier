from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils.translation import override

from .models import PageContentVideo


class VideoBlockTests(SimpleTestCase):
    """The video block waits for the cookie consent and explains why until then."""

    def render(self, video, widget_code=""):
        with override("en"):
            return render_to_string(
                video.get_render_template(),
                {
                    "obj": video,
                    "request": RequestFactory().get("/"),
                    "COOKIERULEZ_WIDGET_CODE": widget_code,
                },
            )

    def test_youtube_plays_without_cookies_at_once_without_the_cookie_banner(self):
        video = PageContentVideo(platform=PageContentVideo.YOUTUBE, video_id="dQw4w9WgXcQ")

        html = self.render(video)

        self.assertIn(' src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"', html)
        self.assertNotIn("data-player-consent", html)

    @override_settings(COOKIERULEZ_WIDGET_CODE="widget")
    def test_with_the_cookie_banner_the_player_waits_and_explains_why(self):
        video = PageContentVideo(platform=PageContentVideo.VIMEO, video_id="76979871")

        html = self.render(video, widget_code="widget")

        self.assertIn(
            'data-src="https://player.vimeo.com/video/76979871?h=5a5572cc05" data-cookierulez="marketing"', html
        )
        self.assertIn("The Vimeo player is not displayed", html)
        self.assertIn('href="https://vimeo.com/76979871"', html)
        self.assertIn(">Watch on Vimeo</a>", html)

    def test_twitch_clip_links_the_clip(self):
        clip = PageContentVideo(platform=PageContentVideo.TWITCH, video_id="clip=FunnyClip-abc")
        channel = PageContentVideo(platform=PageContentVideo.TWITCH, video_id="channel=iai")

        self.assertEqual(clip.embed["link"], "https://clips.twitch.tv/FunnyClip-abc")
        self.assertEqual(channel.embed["link"], "")
