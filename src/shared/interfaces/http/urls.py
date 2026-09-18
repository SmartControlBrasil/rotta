from django.urls import path

from .views import BlogArticleView, PublicPageView

app_name = "public"

OFFICIAL_PUBLIC_PAGES = [
    ("", "public/home.html", "home"),
    ("sobre/", "public/pages/about.html", "about"),
    ("servicos/", "public/pages/service.html", "services"),
    ("servicos/", "public/pages/service.html", "service"),
    ("blog/", "public/blog/index.html", "blog"),
    ("contato/", "public/pages/contact.html", "contact"),
]

urlpatterns = [
    *[
        path(route, PublicPageView.as_view(template_name=template_name), name=name)
        for route, template_name, name in OFFICIAL_PUBLIC_PAGES
    ],
    path("blog/<slug:slug>/", BlogArticleView.as_view(), name="blog_article"),
]
