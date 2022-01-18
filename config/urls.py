"""app URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
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
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(f"admin-{settings.ADMIN_SECRET_SUFFIX}/", admin.site.urls),
    path(
        "accounts/",
        include(("django.contrib.auth.urls", "accounts"), namespace="accounts"),
    ),
    path("explore/", include(("explore.urls", "explore"), namespace="explore")),
    path("profile/", include(("profiles.urls", "profiles"), namespace="profiles")),
    path("images/", include(("images.urls", "images"), namespace="images")),
    path("tags/", include(("tags.urls", "tags"), namespace="tags")),
    path("help/", include(("help.urls", "help"), namespace="help")),
    path("", include(("home.urls", "home"), namespace="home")),
]
