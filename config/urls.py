"""
URL configuration for the OpenVPN Dashboard project.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('openvpn_dashboard.urls')),
]
