import pytest
from django.urls import reverse


@pytest.mark.parametrize(
    "route_name",
    [
        "public:home",
        "public:index",
        "public:index_02",
        "public:index_03",
        "public:index_04",
        "public:about",
        "public:service",
        "public:service_left",
        "public:service_right",
        "public:service_single",
        "public:team",
        "public:testimonial",
        "public:faq",
        "public:pricing",
        "public:contact",
        "public:not_found_demo",
        "public:blog",
        "public:blog_left",
        "public:blog_right",
        "public:blog_single",
        "public:projects",
        "public:project_left",
        "public:project_right",
        "public:project_single",
    ],
)
def test_public_cargon_pages_render(client, route_name):
    response = client.get(reverse(route_name))

    assert response.status_code == 200


def test_home_uses_public_cargon_template(client):
    response = client.get(reverse("public:home"))

    assert response.status_code == 200
    assert any(template.name == "public/home.html" for template in response.templates)
    assert b"Rotta Web" in response.content
