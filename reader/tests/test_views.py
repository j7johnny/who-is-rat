"""Tests for reader views - access enforcement and page serving."""
import pytest
from django.test import Client
from django.urls import reverse

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

    def test_admin_denied(self):
        admin = AdminUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=admin.username, password="TestPass123!")
        response = client.get(reverse("reader:library"))
        assert response.status_code == 403

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
class TestPageImage:
    def test_invalid_signed_key_404(self):
        reader = ReaderUserFactory(password="TestPass123!")
        client = Client()
        client.login(username=reader.username, password="TestPass123!")
        response = client.get(reverse("reader:page", args=["invalid_key", 1]))
        assert response.status_code == 404
