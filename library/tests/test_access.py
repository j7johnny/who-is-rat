"""Tests for the three-tier access control system (site/novel/chapter grants)."""
import pytest

from accounts.tests.factories import ReaderUserFactory
from library.services.access import (
    accessible_chapters_for_novel,
    accessible_chapters_queryset,
    accessible_novels_queryset,
    get_accessible_chapter_by_version,
    get_adjacent_chapters,
    reader_has_chapter_access,
    reader_has_site_access,
)

from .factories import (
    NovelFactory,
    PublishedChapterFactory,
    ReaderChapterGrantFactory,
    ReaderNovelGrantFactory,
    ReaderSiteGrantFactory,
)


@pytest.mark.django_db
class TestReaderHasSiteAccess:
    def test_no_grant(self):
        reader = ReaderUserFactory()
        assert reader_has_site_access(reader) is False

    def test_with_site_grant(self):
        grant = ReaderSiteGrantFactory()
        assert reader_has_site_access(grant.reader) is True


@pytest.mark.django_db
class TestReaderHasChapterAccess:
    def test_no_access(self):
        reader = ReaderUserFactory()
        chapter = PublishedChapterFactory()
        assert reader_has_chapter_access(reader, chapter) is False

    def test_site_grant_gives_access(self):
        grant = ReaderSiteGrantFactory()
        chapter = PublishedChapterFactory()
        assert reader_has_chapter_access(grant.reader, chapter) is True

    def test_novel_grant_gives_access(self):
        chapter = PublishedChapterFactory()
        grant = ReaderNovelGrantFactory(novel=chapter.novel)
        assert reader_has_chapter_access(grant.reader, chapter) is True

    def test_novel_grant_wrong_novel(self):
        chapter = PublishedChapterFactory()
        other_novel = NovelFactory()
        grant = ReaderNovelGrantFactory(novel=other_novel)
        assert reader_has_chapter_access(grant.reader, chapter) is False

    def test_chapter_grant_gives_access(self):
        chapter = PublishedChapterFactory()
        grant = ReaderChapterGrantFactory(chapter=chapter)
        assert reader_has_chapter_access(grant.reader, chapter) is True

    def test_chapter_grant_wrong_chapter(self):
        chapter = PublishedChapterFactory()
        other_chapter = PublishedChapterFactory()
        grant = ReaderChapterGrantFactory(chapter=other_chapter)
        assert reader_has_chapter_access(grant.reader, chapter) is False


@pytest.mark.django_db
class TestAccessibleChaptersQueryset:
    def test_site_grant_sees_all_published(self):
        grant = ReaderSiteGrantFactory()
        ch1 = PublishedChapterFactory()
        ch2 = PublishedChapterFactory()
        result = list(accessible_chapters_queryset(grant.reader))
        assert ch1 in result
        assert ch2 in result

    def test_novel_grant_sees_novel_chapters(self):
        novel = NovelFactory()
        ch1 = PublishedChapterFactory(novel=novel)
        ch2 = PublishedChapterFactory(novel=novel)
        ch3 = PublishedChapterFactory()  # different novel
        grant = ReaderNovelGrantFactory(novel=novel)
        result = list(accessible_chapters_queryset(grant.reader))
        assert ch1 in result
        assert ch2 in result
        assert ch3 not in result

    def test_chapter_grant_sees_only_granted(self):
        ch1 = PublishedChapterFactory()
        ch2 = PublishedChapterFactory()
        grant = ReaderChapterGrantFactory(chapter=ch1)
        result = list(accessible_chapters_queryset(grant.reader))
        assert ch1 in result
        assert ch2 not in result

    def test_no_grant_sees_nothing(self):
        reader = ReaderUserFactory()
        PublishedChapterFactory()
        result = list(accessible_chapters_queryset(reader))
        assert result == []

    def test_draft_chapters_invisible(self):
        """Draft chapters should not appear even with site grant."""
        from library.tests.factories import ChapterFactory

        grant = ReaderSiteGrantFactory()
        ChapterFactory(status="draft")
        result = list(accessible_chapters_queryset(grant.reader))
        assert result == []


@pytest.mark.django_db
class TestAccessibleNovelsQueryset:
    def test_site_grant_sees_novels_with_published_chapters(self):
        grant = ReaderSiteGrantFactory()
        novel = NovelFactory()
        PublishedChapterFactory(novel=novel)
        result = list(accessible_novels_queryset(grant.reader))
        assert novel in result

    def test_novel_without_published_chapters_invisible(self):
        grant = ReaderSiteGrantFactory()
        NovelFactory()  # no chapters
        result = list(accessible_novels_queryset(grant.reader))
        assert result == []

    def test_no_grant_sees_nothing(self):
        reader = ReaderUserFactory()
        novel = NovelFactory()
        PublishedChapterFactory(novel=novel)
        result = list(accessible_novels_queryset(reader))
        assert result == []


@pytest.mark.django_db
class TestAccessibleChaptersForNovel:
    def test_filters_by_novel(self):
        novel = NovelFactory()
        ch1 = PublishedChapterFactory(novel=novel)
        PublishedChapterFactory()  # different novel
        grant = ReaderSiteGrantFactory()
        result = list(accessible_chapters_for_novel(grant.reader, novel))
        assert result == [ch1]


@pytest.mark.django_db
class TestGetAccessibleChapterByVersion:
    def test_found(self):
        chapter = PublishedChapterFactory()
        grant = ReaderSiteGrantFactory()
        result = get_accessible_chapter_by_version(grant.reader, chapter.current_version_id)
        assert result == chapter

    def test_not_found(self):
        reader = ReaderUserFactory()
        chapter = PublishedChapterFactory()
        result = get_accessible_chapter_by_version(reader, chapter.current_version_id)
        assert result is None


@pytest.mark.django_db
class TestGetAdjacentChapters:
    def test_adjacent_chapters(self):
        novel = NovelFactory()
        ch1 = PublishedChapterFactory(novel=novel, sort_order=1)
        ch2 = PublishedChapterFactory(novel=novel, sort_order=2)
        ch3 = PublishedChapterFactory(novel=novel, sort_order=3)
        grant = ReaderSiteGrantFactory()
        prev_ch, next_ch = get_adjacent_chapters(grant.reader, ch2)
        assert prev_ch == ch1
        assert next_ch == ch3

    def test_first_chapter_has_no_previous(self):
        novel = NovelFactory()
        ch1 = PublishedChapterFactory(novel=novel, sort_order=1)
        PublishedChapterFactory(novel=novel, sort_order=2)
        grant = ReaderSiteGrantFactory()
        prev_ch, _ = get_adjacent_chapters(grant.reader, ch1)
        assert prev_ch is None

    def test_last_chapter_has_no_next(self):
        novel = NovelFactory()
        PublishedChapterFactory(novel=novel, sort_order=1)
        ch2 = PublishedChapterFactory(novel=novel, sort_order=2)
        grant = ReaderSiteGrantFactory()
        _, next_ch = get_adjacent_chapters(grant.reader, ch2)
        assert next_ch is None
