"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core import views
from core.forms import ChangePasswordForm, LoginForm, ResetPasswordForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(authentication_form=LoginForm),
        name="login",
    ),
    path(
        "password/",
        auth_views.PasswordChangeView.as_view(
            form_class=ChangePasswordForm, success_url="/"
        ),
        name="password_change",
    ),
    path(
        "forgot/",
        auth_views.PasswordResetView.as_view(
            email_template_name="registration/password_reset_email.txt",
            subject_template_name="registration/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "forgot/sent/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "forgot/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(form_class=ResetPasswordForm),
        name="password_reset_confirm",
    ),
    path(
        "forgot/done/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("profile/", views.profile, name="profile"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("chat/", include("chat.urls")),
    path("meetings/", include("meetings.urls")),
    path("tasks/", include("tasks.urls")),
    path("plans/", include("plans.urls")),
    path("notifications/", include("notifications.urls")),
    path("", views.home, name="home"),
]
