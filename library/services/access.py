from __future__ import annotations

from django.db.models import Count, Q, QuerySet

from accounts.models import User
from library.models import Chapter, ChapterStatus, Novel, ReaderChapterGrant, ReaderNovelGrant, ReaderSiteGrant


def reader_has_site_access(reader: User) -> bool:
    if reader.role == User.Role.ADMIN:
        return True
    return ReaderSiteGrant.objects.filter(reader=reader).exists()


def accessible_chapters_queryset(reader: User) -> QuerySet[Chapter]:
    queryset = (
        Chapter.objects.select_related("novel", "current_version")
        .filter(status=ChapterStatus.PUBLISHED, current_version__isnull=False)
        .order_by("novel__title", "sort_order", "id")
    )
    if reader_has_site_access(reader):
        return queryset

    return queryset.filter(
        Q(reader_grants__reader=reader) |
        Q(novel__reader_novel_grants__reader=reader)
    ).distinct()


def accessible_novels_queryset(reader: User) -> QuerySet[Novel]:
    published_filter = Q(chapters__status=ChapterStatus.PUBLISHED, chapters__current_version__isnull=False)
    if reader_has_site_access(reader):
        return (
            Novel.objects.filter(is_active=True)
            .annotate(chapter_count=Count("chapters", filter=published_filter, distinct=True))
            .filter(chapter_count__gt=0)
            .order_by("title")
        )

    accessible_filter = published_filter & (
        Q(chapters__reader_grants__reader=reader) |
        Q(reader_novel_grants__reader=reader)
    )
    return (
        Novel.objects.filter(is_active=True)
        .annotate(chapter_count=Count("chapters", filter=accessible_filter, distinct=True))
        .filter(chapter_count__gt=0)
        .order_by("title")
    )


def reader_has_chapter_access(reader: User, chapter: Chapter) -> bool:
    if reader_has_site_access(reader):
        return True
    if ReaderNovelGrant.objects.filter(reader=reader, novel=chapter.novel).exists():
        return True
    return ReaderChapterGrant.objects.filter(reader=reader, chapter=chapter).exists()


def get_accessible_chapter_by_version(reader: User, version_id: int) -> Chapter | None:
    return accessible_chapters_queryset(reader).filter(current_version_id=version_id).first()


def get_adjacent_chapters(reader: User, chapter: Chapter) -> tuple[Chapter | None, Chapter | None]:
    queryset = accessible_chapters_queryset(reader).filter(novel=chapter.novel)
    previous_chapter = queryset.filter(
        Q(sort_order__lt=chapter.sort_order) |
        Q(sort_order=chapter.sort_order, id__lt=chapter.id)
    ).order_by("-sort_order", "-id").first()
    next_chapter = queryset.filter(
        Q(sort_order__gt=chapter.sort_order) |
        Q(sort_order=chapter.sort_order, id__gt=chapter.id)
    ).order_by("sort_order", "id").first()
    return previous_chapter, next_chapter


def accessible_chapters_for_novel(reader: User, novel: Novel) -> QuerySet[Chapter]:
    return accessible_chapters_queryset(reader).filter(novel=novel)
