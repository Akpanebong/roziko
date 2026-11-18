from django.contrib import admin
from django.conf import settings
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("desk.urls")),
]

# Serve project-level static assets while running Django's development server.
# Production should serve STATIC_ROOT through the web server after collectstatic.
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
