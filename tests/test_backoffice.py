import pytest
from django.urls import reverse


def test_public_home_still_renders(client):
    response = client.get(reverse("public:home"))

    assert response.status_code == 200
    assert any(template.name == "public/home.html" for template in response.templates)


def test_backoffice_dashboard_requires_authentication(client):
    response = client.get(reverse("backoffice:dashboard"))

    assert response.status_code == 302
    assert response["Location"].startswith(reverse("backoffice:login"))


@pytest.mark.django_db
def test_backoffice_login_valid_user_redirects_to_dashboard(client, django_user_model):
    django_user_model.objects.create_user(username="operator", password="safe-pass-123")

    response = client.post(
        reverse("backoffice:login"),
        {"username": "operator", "password": "safe-pass-123"},
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("backoffice:dashboard")


@pytest.mark.django_db
def test_backoffice_dashboard_authenticated_uses_nexadash_template(client, django_user_model):
    user = django_user_model.objects.create_user(username="operator", password="safe-pass-123")
    client.force_login(user)

    response = client.get(reverse("backoffice:dashboard"))

    assert response.status_code == 200
    assert any(template.name == "backoffice/dashboard.html" for template in response.templates)
    assert b"Rotta Backoffice" in response.content
    assert b"backoffice/nexadash/css/style.css" in response.content


@pytest.mark.django_db
def test_backoffice_logout_returns_to_login(client, django_user_model):
    user = django_user_model.objects.create_user(username="operator", password="safe-pass-123")
    client.force_login(user)

    response = client.post(reverse("backoffice:logout"))

    assert response.status_code == 302
    assert response["Location"] == reverse("backoffice:login")
