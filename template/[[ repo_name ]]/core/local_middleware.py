"""Middleware of the local development only, see core/settings/local.py."""

from django_browser_reload.middleware import BrowserReloadMiddleware


def is_editor_page(request):
    """The pages of the Editor.js editors, each in an iframe of a form."""
    return request.path.startswith("/editor-js/") or "/editor-js/" in request.path


class PageBrowserReloadMiddleware(BrowserReloadMiddleware):
    """Reloads the pages, not the editors in their iframes: the script keeps an
    event stream open, and a form with many editors would hold as many threads
    of the development server, the other requests of the page waiting."""

    def maybe_inject(self, request, response):
        if is_editor_page(request):
            return
        super().maybe_inject(request, response)
