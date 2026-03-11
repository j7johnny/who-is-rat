from django.urls import path

from .views import ReaderLoginView, ReaderLogoutView, ReaderPasswordChangeView

urlpatterns = [
    path("login", ReaderLoginView.as_view(), name="login"),
    path("logout", ReaderLogoutView.as_view(), name="logout"),
    path("me/password", ReaderPasswordChangeView.as_view(), name="password-change"),
]
