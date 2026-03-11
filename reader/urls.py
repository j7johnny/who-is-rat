from django.urls import path

from .views import chapter_detail, library_index, novel_detail, reader_page_image

app_name = "reader"

urlpatterns = [
    path("library", library_index, name="library"),
    path("novels/<int:novel_id>", novel_detail, name="novel-detail"),
    path("chapters/<int:chapter_id>", chapter_detail, name="chapter-detail"),
    path("pages/<str:signed_key>/<int:page_index>.png", reader_page_image, name="page"),
]
