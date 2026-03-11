from django.conf import settings


def app_meta(request):
    return {
        "app_version": getattr(settings, "APP_VERSION", "v0.0.0"),
    }
