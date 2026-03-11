from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("health/", views.health_check, name="health"),
    path("v1/chapters/<int:chapter_id>/publish-status/", views.chapter_publish_status, name="chapter-publish-status"),
    path("v1/chapters/<int:chapter_id>/publish-progress/", views.chapter_publish_progress_sse, name="chapter-publish-progress"),
    path("v1/extraction/<int:record_id>/status/", views.extraction_status, name="extraction-status"),
    path("v1/extraction/<int:record_id>/progress/", views.extraction_progress_sse, name="extraction-progress"),
    path("v1/extraction/<int:record_id>/stop/", views.extraction_stop, name="extraction-stop"),
    path("schema/", views.schema_view, name="schema"),
]
