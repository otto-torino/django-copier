from django.urls import path

from .feed import NewsFeed
from .views import NewsDetailView, NewsListView

app_name = "news"

urlpatterns = [
    path("feed/", NewsFeed(), name="feed"),
    path("", NewsListView.as_view(), name="list"),
    path(
        "<int:year>/<int:month>/<int:day>/<slug:slug>/",
        NewsDetailView.as_view(),
        name="detail",
    ),
]
