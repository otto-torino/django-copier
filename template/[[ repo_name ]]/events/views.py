from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import DetailView, ListView

from .models import Event


class EventListView(ListView):
    model = Event
    paginate_by = 9

    def get_queryset(self):
        return (
            Event.objects.accessible_by(
                self.request.user,
                site=get_current_site(self.request),
            )
            .current()
            .prefetch_related("tags")
            .distinct()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["breadcrumbs"] = [
            {"label": _("Home"), "url": reverse("home")},
            {"label": _("Events")},
        ]
        return context


class EventDetailView(DetailView):
    model = Event

    def get_queryset(self):
        return (
            Event.objects.accessible_by(
                self.request.user,
                site=get_current_site(self.request),
            )
            .filter(
                date__year=self.kwargs["year"],
                date__month=self.kwargs["month"],
                date__day=self.kwargs["day"],
            )
            .prefetch_related("tags")
        )
