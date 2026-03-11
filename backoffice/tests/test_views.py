"""Tests for backoffice views - admin access and setup."""
import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from accounts.tests.factories import AdminUserFactory, ReaderUserFactory


@pytest.mark.django_db
class TestSetupView:
    def test_setup_page_available_when_no_admin(self):
        client = Client()
        response = client.get(reverse("backoffice:setup"))
        assert response.status_code == 200

    def test_setup_page_404_when_admin_exists(self):
        AdminUserFactory()
        client = Client()
        response = client.get(reverse("backoffice:setup"))
        assert response.status_code == 404

    def test_setup_creates_admin(self):
        client = Client()
        response = client.post(
            reverse("backoffice:setup"),
            {
                "username": "firstadmin",
                "password1": "SecurePass123!",
                "password2": "SecurePass123!",
            },
        )
        assert response.status_code == 302
        assert User.objects.filter(username="firstadmin", role=User.Role.ADMIN).exists()

    def test_setup_password_mismatch(self):
        client = Client()
        response = client.post(
            reverse("backoffice:setup"),
            {
                "username": "firstadmin",
                "password1": "SecurePass123!",
                "password2": "DifferentPass456!",
            },
        )
        assert response.status_code == 200
        assert not User.objects.filter(username="firstadmin").exists()


@pytest.mark.django_db
class TestDashboard:
    def test_requires_admin(self):
        client = Client()
        response = client.get(reverse("backoffice:dashboard"))
        assert response.status_code == 302

    def test_reader_denied(self):
        reader = ReaderUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.get(reverse("backoffice:dashboard"))
        assert response.status_code == 403

    def test_admin_can_access(self):
        admin = AdminUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=admin.username, password="TestPass123!")
        response = client.get(reverse("backoffice:dashboard"))
        assert response.status_code == 200


@pytest.mark.django_db
class TestReaderManagement:
    def test_reader_list(self):
        admin = AdminUserFactory(password="TestPass123!")
        ReaderUserFactory(username="testreader")
        client = Client()
        client.login(username=admin.username, password="TestPass123!")
        response = client.get(reverse("backoffice:reader-list"))
        assert response.status_code == 200
        assert "testreader" in response.content.decode()

    def test_reader_create(self):
        admin = AdminUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=admin.username, password="TestPass123!")
        response = client.post(
            reverse("backoffice:reader-create"),
            {
                "username": "newreader",
                "password1": "ReaderPass123!",
                "password2": "ReaderPass123!",
                "is_active": "on",
            },
        )
        assert response.status_code == 302
        assert User.objects.filter(username="newreader", role=User.Role.READER).exists()


@pytest.mark.django_db
class TestNovelManagement:
    def test_novel_list(self):
        admin = AdminUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=admin.username, password="TestPass123!")
        response = client.get(reverse("backoffice:novel-list"))
        assert response.status_code == 200

    def test_novel_create(self):
        admin = AdminUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=admin.username, password="TestPass123!")
        response = client.post(
            reverse("backoffice:novel-create"),
            {
                "title": "測試小說",
                "slug": "test-novel",
                "description": "這是測試",
                "is_active": "on",
            },
        )
        assert response.status_code == 302


@pytest.mark.django_db
class TestHealthEndpoint:
    def test_health_check_ok(self):
        client = Client()
        response = client.get("/health/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["db"] is True

    def test_api_health_also_works(self):
        client = Client()
        response = client.get("/api/health/")
        assert response.status_code == 200
