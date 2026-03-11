"""Tests for login, logout, and password change views."""
import pytest
from django.test import Client
from django.urls import reverse

from .factories import AdminUserFactory, ReaderUserFactory


@pytest.fixture(autouse=True)
def _ensure_admin_exists(db):
    """Ensure an admin account exists so login page doesn't redirect to /setup/."""
    AdminUserFactory(username="sysadmin")


@pytest.mark.django_db
class TestReaderLogin:
    def test_login_page_loads(self):
        client = Client()
        response = client.get(reverse("login"))
        assert response.status_code == 200

    def test_login_success(self):
        reader = ReaderUserFactory(password="TestPass123!")
        client = Client()
        response = client.post(
            reverse("login"),
            {"username": reader.username, "password": "TestPass123!"},
            follow=True,
        )
        assert response.status_code == 200
        assert response.wsgi_request.user.is_authenticated

    def test_login_wrong_password(self):
        reader = ReaderUserFactory(password="TestPass123!")
        client = Client()
        response = client.post(reverse("login"), {"username": reader.username, "password": "WrongPass456!"})
        assert response.status_code == 200
        assert not response.wsgi_request.user.is_authenticated

    def test_login_nonexistent_user(self):
        client = Client()
        response = client.post(reverse("login"), {"username": "nouser", "password": "TestPass123!"})
        assert response.status_code == 200
        assert not response.wsgi_request.user.is_authenticated

    def test_login_inactive_user(self):
        reader = ReaderUserFactory(password="TestPass123!", is_active=False)
        client = Client()
        response = client.post(reverse("login"), {"username": reader.username, "password": "TestPass123!"})
        assert response.status_code == 200
        assert not response.wsgi_request.user.is_authenticated


@pytest.mark.django_db
class TestLogout:
    def test_logout(self):
        reader = ReaderUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.get(reverse("logout"))
        assert response.status_code == 302


@pytest.mark.django_db
class TestPasswordChange:
    def test_change_password_page_requires_auth(self):
        client = Client()
        response = client.get(reverse("password-change"))
        assert response.status_code == 302

    def test_change_password_success(self):
        reader = ReaderUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.post(
            reverse("password-change"),
            {
                "old_password": "TestPass123!",
                "new_password1": "NewTestPass456!",
                "new_password2": "NewTestPass456!",
            },
        )
        assert response.status_code == 302
        reader.refresh_from_db()
        assert reader.check_password("NewTestPass456!")
        assert reader.password_changed_at is not None

    def test_change_password_wrong_old(self):
        reader = ReaderUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.post(
            reverse("password-change"),
            {
                "old_password": "WrongOld123!",
                "new_password1": "NewTestPass456!",
                "new_password2": "NewTestPass456!",
            },
        )
        assert response.status_code == 200
        reader.refresh_from_db()
        assert reader.check_password("TestPass123!")


@pytest.mark.django_db
class TestHomeRedirect:
    def test_unauthenticated_redirects_to_login(self):
        client = Client()
        response = client.get("/")
        assert response.status_code == 302
        assert "login" in response.url

    def test_reader_redirects_to_library(self):
        reader = ReaderUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.get("/")
        assert response.status_code == 302
        assert "reader" in response.url or "library" in response.url

    def test_admin_redirects_to_dashboard(self):
        client = Client()
        client.login(username="sysadmin", password="TestPass123!")
        response = client.get("/")
        assert response.status_code == 302
        assert "manage" in response.url

    def test_no_admin_redirects_to_setup(self):
        """When no admin exists, should redirect to setup.

        Note: This test needs its own DB state without the autouse fixture admin.
        We delete the admin created by the fixture.
        """
        from accounts.models import User

        User.objects.filter(role=User.Role.ADMIN).delete()
        client = Client()
        response = client.get("/")
        assert response.status_code == 302
        assert "setup" in response.url
