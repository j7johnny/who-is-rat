import hashlib

import factory

from accounts.tests.factories import AdminUserFactory, ReaderUserFactory
from library.models import (
    AntiOcrPreset,
    BasePage,
    Chapter,
    ChapterPublishJob,
    ChapterStatus,
    ChapterVersion,
    Novel,
    ReaderChapterGrant,
    ReaderNovelGrant,
    ReaderSiteGrant,
)


class NovelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Novel

    title = factory.Sequence(lambda n: f"測試小說 {n}")
    slug = factory.Sequence(lambda n: f"test-novel-{n}")
    description = "這是一本測試小說。"
    is_active = True


class AntiOcrPresetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AntiOcrPreset

    name = factory.Sequence(lambda n: f"測試設定 {n}")
    is_default = False


class ChapterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Chapter

    novel = factory.SubFactory(NovelFactory)
    title = factory.Sequence(lambda n: f"第 {n} 章")
    sort_order = factory.Sequence(lambda n: n)
    content = "這是章節的測試內容，包含足夠的中文字數進行測試。" * 5
    status = ChapterStatus.DRAFT


class ChapterVersionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChapterVersion

    chapter = factory.SubFactory(ChapterFactory)
    version_number = 1
    content = factory.LazyAttribute(lambda o: o.chapter.content)
    source_sha256 = factory.LazyAttribute(lambda o: hashlib.sha256(o.content.encode()).hexdigest())
    preset_snapshot = factory.LazyFunction(dict)
    created_by = factory.SubFactory(AdminUserFactory)


class PublishedChapterFactory(ChapterFactory):
    status = ChapterStatus.PUBLISHED

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        chapter = super()._create(model_class, *args, **kwargs)
        version = ChapterVersionFactory(chapter=chapter)
        chapter.current_version = version
        chapter.save(update_fields=["current_version"])
        return chapter


class ChapterPublishJobFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChapterPublishJob

    chapter = factory.SubFactory(ChapterFactory)
    chapter_version = factory.SubFactory(ChapterVersionFactory)
    status = ChapterPublishJob.Status.PENDING
    created_by = factory.SubFactory(AdminUserFactory)


class BasePageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BasePage

    chapter_version = factory.SubFactory(ChapterVersionFactory)
    device_profile = "desktop"
    page_index = 0
    relative_path = factory.Sequence(lambda n: f"base_pages/test/page_{n}.png")
    char_count = 200
    image_width = 600
    image_height = 400


class ReaderSiteGrantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ReaderSiteGrant

    reader = factory.SubFactory(ReaderUserFactory)
    granted_by = factory.SubFactory(AdminUserFactory)


class ReaderNovelGrantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ReaderNovelGrant

    reader = factory.SubFactory(ReaderUserFactory)
    novel = factory.SubFactory(NovelFactory)
    granted_by = factory.SubFactory(AdminUserFactory)


class ReaderChapterGrantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ReaderChapterGrant

    reader = factory.SubFactory(ReaderUserFactory)
    chapter = factory.SubFactory(ChapterFactory)
    granted_by = factory.SubFactory(AdminUserFactory)
