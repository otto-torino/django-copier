from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import DetailView, ListView

from search_app.related import get_related_content

from .models import NewsArticle


class NewsListView(ListView):
    model = NewsArticle
    paginate_by = 9

    def get_queryset(self):
        return (
            NewsArticle.objects.accessible_by(
                self.request.user,
                site=get_current_site(self.request),
            )
            .prefetch_related("tags")
            .distinct()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["breadcrumbs"] = [
            {"label": _("Home"), "url": reverse("home")},
            {"label": _("News")},
        ]
        return context


class NewsDetailView(DetailView):
    model = NewsArticle

    def get_queryset(self):
        return (
            NewsArticle.objects.accessible_by(
                self.request.user,
                site=get_current_site(self.request),
            )
            .filter(
                publication_date__year=self.kwargs["year"],
                publication_date__month=self.kwargs["month"],
                publication_date__day=self.kwargs["day"],
            )
            .prefetch_related("tags")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["related_content"] = get_related_content(
            self.object, self.request
        )
        return context
