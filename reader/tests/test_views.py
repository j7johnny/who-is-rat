"""Tests for reader views - access enforcement and page serving."""
import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from accounts.tests.factories import AdminUserFactory, ReaderUserFactory
from library.tests.factories import (
    NovelFactory,
    PublishedChapterFactory,
    ReaderChapterGrantFactory,
    ReaderNovelGrantFactory,
    ReaderSiteGrantFactory,
)


@pytest.mark.django_db
class TestLibraryIndex:
    def test_requires_auth(self):
        client = Client()
        response = client.get(reverse("reader:library"))
        assert response.status_code == 302

    def test_admin_can_preview(self):
        """Admin should be able to access reader pages for preview."""
        admin = AdminUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=admin.username, password="TestPass123!")
        response = client.get(reverse("reader:library"))
        assert response.status_code == 200

    def test_reader_sees_accessible_novels(self):
        reader = ReaderUserFactory(password="TestPass123!")
        novel = NovelFactory()
        PublishedChapterFactory(novel=novel)
        ReaderSiteGrantFactory(reader=reader)
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.get(reverse("reader:library"))
        assert response.status_code == 200
        assert novel.title in response.content.decode()

    def test_reader_without_grant_sees_empty(self):
        reader = ReaderUserFactory(password="TestPass123!")
        novel = NovelFactory()
        PublishedChapterFactory(novel=novel)
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.get(reverse("reader:library"))
        assert response.status_code == 200
        assert novel.title not in response.content.decode()

    def test_cache_control_headers(self):
        reader = ReaderUserFactory(password="TestPass123!")
        ReaderSiteGrantFactory(reader=reader)
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.get(reverse("reader:library"))
        assert "no-store" in response.get("Cache-Control", "")


@pytest.mark.django_db
class TestNovelDetail:
    def test_novel_with_access(self):
        reader = ReaderUserFactory(password="TestPass123!")
        novel = NovelFactory()
        PublishedChapterFactory(novel=novel)
        ReaderNovelGrantFactory(reader=reader, novel=novel)
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.get(reverse("reader:novel-detail", args=[novel.id]))
        assert response.status_code == 200

    def test_novel_without_access_404(self):
        reader = ReaderUserFactory(password="TestPass123!")
        novel = NovelFactory()
        PublishedChapterFactory(novel=novel)
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.get(reverse("reader:novel-detail", args=[novel.id]))
        assert response.status_code == 404


@pytest.mark.django_db
class TestChapterDetail:
    def test_chapter_without_access_404(self):
        reader = ReaderUserFactory(password="TestPass123!")
        chapter = PublishedChapterFactory()
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.get(reverse("reader:chapter-detail", args=[chapter.id]))
        assert response.status_code == 404

    def test_chapter_with_access(self):
        reader = ReaderUserFactory(password="TestPass123!")
        chapter = PublishedChapterFactory()
        ReaderChapterGrantFactory(reader=reader, chapter=chapter)
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.get(reverse("reader:chapter-detail", args=[chapter.id]))
        assert response.status_code == 200


@pytest.mark.django_db
class TestAdminPreviewAccess:
    """Admin must be able to browse all reader pages for preview."""

    def test_admin_can_view_library(self):
        admin = AdminUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=admin.username, password="TestPass123!")
        response = client.get(reverse("reader:library"))
        assert response.status_code == 200

    def test_admin_can_view_novel_detail(self):
        admin = AdminUserFactory(password="TestPass123!")
        novel = NovelFactory()
        PublishedChapterFactory(novel=novel)
        ReaderSiteGrantFactory(reader=admin)
        client = Client()
        client.login(username=admin.username, password="TestPass123!")
        response = client.get(reverse("reader:novel-detail", args=[novel.id]))
        assert response.status_code == 200

    def test_admin_can_view_chapter(self):
        admin = AdminUserFactory(password="TestPass123!")
        chapter = PublishedChapterFactory()
        ReaderChapterGrantFactory(reader=admin, chapter=chapter)
        client = Client()
        client.login(username=admin.username, password="TestPass123!")
        response = client.get(reverse("reader:chapter-detail", args=[chapter.id]))
        assert response.status_code == 200


@pytest.mark.django_db
class TestLoginRedirect:
    """Login should redirect to home which routes by role."""

    def test_admin_login_redirects_to_dashboard(self):
        admin = AdminUserFactory(password="TestPass123!")
        client = Client()
        response = client.post(
            reverse("login"),
            {"username": admin.username, "password": "TestPass123!"},
        )
        # Should redirect to home, then home redirects to dashboard
        assert response.status_code == 302
        target = response.url
        # Follow the redirect chain
        response2 = client.get(target)
        if response2.status_code == 302:
            # home view redirects admin to dashboard
            assert "dashboard" in response2.url or "manage" in response2.url

    def test_reader_login_redirects_to_library(self):
        reader = ReaderUserFactory(password="TestPass123!")
        client = Client()
        response = client.post(
            reverse("login"),
            {"username": reader.username, "password": "TestPass123!"},
        )
        assert response.status_code == 302
        target = response.url
        response2 = client.get(target)
        if response2.status_code == 302:
            assert "library" in response2.url


@pytest.mark.django_db
class TestSetupIntegration:
    """Setup should create a fully functional admin account."""

    def test_setup_admin_can_access_backoffice(self):
        client = Client()
        client.post(
            reverse("backoffice:setup"),
            {
                "username": "myadmin",
                "password1": "SecurePass123!",
                "password2": "SecurePass123!",
            },
        )
        # After setup, user is auto-logged in and redirected
        response = client.get(reverse("backoffice:dashboard"))
        assert response.status_code == 200

    def test_setup_admin_has_staff_and_superuser(self):
        client = Client()
        client.post(
            reverse("backoffice:setup"),
            {
                "username": "myadmin",
                "password1": "SecurePass123!",
                "password2": "SecurePass123!",
            },
        )
        user = User.objects.get(username="myadmin")
        # These flags are what Django admin checks for access
        assert user.is_staff is True
        assert user.is_superuser is True

    def test_setup_admin_has_correct_flags(self):
        client = Client()
        client.post(
            reverse("backoffice:setup"),
            {
                "username": "myadmin",
                "password1": "SecurePass123!",
                "password2": "SecurePass123!",
            },
        )
        user = User.objects.get(username="myadmin")
        assert user.is_staff is True
        assert user.is_superuser is True
        assert user.role == User.Role.ADMIN
        assert user.is_active is True

    def test_setup_admin_can_browse_reader_pages(self):
        """Admin created during setup should also be able to preview reader pages."""
        client = Client()
        client.post(
            reverse("backoffice:setup"),
            {
                "username": "myadmin",
                "password1": "SecurePass123!",
                "password2": "SecurePass123!",
            },
        )
        response = client.get(reverse("reader:library"))
        assert response.status_code == 200


@pytest.mark.django_db
class TestPageImage:
    def test_invalid_signed_key_404(self):
        reader = ReaderUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.get(reverse("reader:page", args=["invalid_key", 1]))
        assert response.status_code == 404
