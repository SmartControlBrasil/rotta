from django.urls import path

from .views import PublicPageView

app_name = "public"

PUBLIC_PAGES = [
    ("", "public/home.html", "home"),
    ("index/", "public/pages/index.html", "index"),
    ("index-02/", "public/pages/index-02.html", "index_02"),
    ("index-03/", "public/pages/index-03.html", "index_03"),
    ("index-04/", "public/pages/index-04.html", "index_04"),
    ("about/", "public/pages/about.html", "about"),
    ("service/", "public/pages/service.html", "service"),
    ("service-left/", "public/pages/service-left.html", "service_left"),
    ("service-right/", "public/pages/service-right.html", "service_right"),
    ("service-single/", "public/pages/service-single.html", "service_single"),
    ("team/", "public/pages/team.html", "team"),
    ("testimonial/", "public/pages/testimonial.html", "testimonial"),
    ("faq/", "public/pages/faq.html", "faq"),
    ("pricing/", "public/pages/pricing.html", "pricing"),
    ("contact/", "public/pages/contact.html", "contact"),
    ("404/", "public/pages/404.html", "not_found_demo"),
    ("blog/", "public/pages/blog.html", "blog"),
    ("blog-left/", "public/pages/blog-left.html", "blog_left"),
    ("blog-right/", "public/pages/blog-right.html", "blog_right"),
    ("blog-single/", "public/pages/blog-single.html", "blog_single"),
    ("projects/", "public/pages/projects.html", "projects"),
    ("project-left/", "public/pages/project-left.html", "project_left"),
    ("project-right/", "public/pages/project-right.html", "project_right"),
    ("project-single/", "public/pages/project-single.html", "project_single"),
]

urlpatterns = [
    path(route, PublicPageView.as_view(template_name=template_name), name=name)
    for route, template_name, name in PUBLIC_PAGES
]
