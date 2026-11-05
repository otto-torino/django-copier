from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils.translation import override

from django.core.exceptions import ValidationError

from .models import PageContentVideo, parse_video_link


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
            'data-src="https://player.vimeo.com/video/76979871" data-cookierulez="marketing"', html
        )
        self.assertIn("The Vimeo player is not displayed", html)
        self.assertIn('href="https://vimeo.com/76979871"', html)
        self.assertIn(">Watch on Vimeo</a>", html)

    def test_twitch_clip_links_the_clip(self):
        clip = PageContentVideo(platform=PageContentVideo.TWITCH, video_id="clip=FunnyClip-abc")
        channel = PageContentVideo(platform=PageContentVideo.TWITCH, video_id="channel=iai")

        self.assertEqual(clip.embed["link"], "https://clips.twitch.tv/FunnyClip-abc")
        self.assertEqual(channel.embed["link"], "")

    def test_an_unlisted_vimeo_video_keeps_its_hash(self):
        for video_id in ("76979871?h=abc123", "76979871/abc123"):
            embed = PageContentVideo(platform=PageContentVideo.VIMEO, video_id=video_id).embed

            self.assertEqual(embed["url"], "https://player.vimeo.com/video/76979871?h=abc123")
            self.assertEqual(embed["link"], "https://vimeo.com/76979871/abc123")

    def test_the_link_of_a_video_gives_its_platform_and_id(self):
        cases = {
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s": (PageContentVideo.YOUTUBE, "dQw4w9WgXcQ"),
            "https://youtu.be/dQw4w9WgXcQ?si=abc": (PageContentVideo.YOUTUBE, "dQw4w9WgXcQ"),
            "https://www.youtube.com/shorts/dQw4w9WgXcQ": (PageContentVideo.YOUTUBE, "dQw4w9WgXcQ"),
            "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ": (PageContentVideo.YOUTUBE, "dQw4w9WgXcQ"),
            "https://vimeo.com/76979871": (PageContentVideo.VIMEO, "76979871"),
            "https://vimeo.com/76979871/abc123": (PageContentVideo.VIMEO, "76979871?h=abc123"),
            "https://player.vimeo.com/video/76979871?h=abc123": (PageContentVideo.VIMEO, "76979871?h=abc123"),
            "https://vimeo.com/channels/staffpicks/76979871": (PageContentVideo.VIMEO, "76979871"),
            "https://clips.twitch.tv/FunnyClip-abc": (PageContentVideo.TWITCH, "clip=FunnyClip-abc"),
            "https://www.twitch.tv/iai/clip/FunnyClip-abc": (PageContentVideo.TWITCH, "clip=FunnyClip-abc"),
            "https://example.com/video/1": None,
        }
        for link, expected in cases.items():
            with self.subTest(link=link):
                self.assertEqual(parse_video_link(link), expected)

    def test_a_pasted_link_sets_the_platform_and_the_id(self):
        video = PageContentVideo(platform=PageContentVideo.YOUTUBE, video_id="https://vimeo.com/76979871/abc123")

        video.clean()

        self.assertEqual(video.platform, PageContentVideo.VIMEO)
        self.assertEqual(video.video_id, "76979871?h=abc123")

    def test_a_link_to_another_site_is_refused(self):
        video = PageContentVideo(video_id="https://example.com/video/1")

        with self.assertRaises(ValidationError) as error:
            video.clean()

        self.assertIn("video_id", error.exception.message_dict)
