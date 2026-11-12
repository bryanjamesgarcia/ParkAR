from django.contrib import admin
from django.urls import include, path
from core.views import app_shell
from core.views_static import service_worker

urlpatterns = [path("admin/", admin.site.urls), path("api/v1/", include("core.urls")), path("service-worker.js", service_worker), path("", app_shell, name="app")]
