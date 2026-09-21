from django.urls import path

from .feed import EventsFeed
from .views import EventDetailView, EventListView

app_name = "events"

urlpatterns = [
    path("feed/", EventsFeed(), name="feed"),
    path("", EventListView.as_view(), name="list"),
    path(
        "<int:year>/<int:month>/<int:day>/<slug:slug>/",
        EventDetailView.as_view(),
        name="detail",
    ),
]
