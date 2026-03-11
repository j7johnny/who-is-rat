from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from library.api.views import health_check
from reader import views as reader_views

urlpatterns = [
    path("", reader_views.home, name="home"),
    path("health/", health_check, name="health"),
    path("", include("accounts.urls")),
    path("", include("backoffice.urls")),
    path("reader/", include("reader.urls")),
    path("api/", include("library.api.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
