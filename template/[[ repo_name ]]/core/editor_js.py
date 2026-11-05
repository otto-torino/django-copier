from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from editor_js.renderers import EditorJsRenderer

# The names of the services of the EditorJS embed tool, where the title
# casing of the service is not the name of the platform.
EMBED_PLATFORMS = {
    "youtube": "YouTube",
    "twitch-video": "Twitch",
    "twitch-channel": "Twitch",
    "twitter": "X",
    "codepen": "CodePen",
    "github": "GitHub",
}
# The services that play audio or video: their note speaks of a player.
EMBED_PLAYERS = {"youtube", "vimeo", "twitch-video", "twitch-channel", "coub"}


class SiteEditorJsRenderer(EditorJsRenderer):
    """Render EditorJS content, with the embeds waiting for the cookie consent."""

    def render_embed(self, data):
        """An embedded content that waits for the cookie consent, like the video blocks.

        The platforms set their own cookies: with Cookie Rulez the iframe gets
        its src only once the marketing cookies are accepted, and the note
        after it explains why until then, see ``includes/consent_note.html``.
        YouTube plays from the domain without cookies until the video starts.
        """
        service = data.get("service", "")
        embed_url = data.get("embed", "").replace(
            "https://www.youtube.com/embed/", "https://www.youtube-nocookie.com/embed/"
        )
        if not embed_url:
            return ""
        caption = self.clean_inline(data.get("caption", ""))
        platform = EMBED_PLATFORMS.get(service, service.replace("-", " ").title())

        if settings.COOKIERULEZ_WIDGET_CODE:
            iframe = format_html(
                '<iframe class="[&:not([src^=http])]:hidden" data-src="{}" data-cookierulez="marketing" '
                'title="{}" frameborder="0" allowfullscreen loading="lazy"></iframe>',
                embed_url,
                platform,
            )
            note = render_to_string(
                "includes/consent_note.html",
                {
                    "platform": platform,
                    "link": data.get("source", ""),
                    "kind": "player" if service in EMBED_PLAYERS else "content",
                },
            )
        else:
            iframe = format_html(
                '<iframe src="{}" title="{}" frameborder="0" allowfullscreen loading="lazy"></iframe>',
                embed_url,
                platform,
            )
            note = ""

        return format_html(
            '<figure class="embed-figure embed-{}"><div class="embed-responsive-wrapper">{}{}</div>'
            "<figcaption>{}</figcaption></figure>",
            service,
            iframe,
            mark_safe(note),
            mark_safe(caption),
        )
