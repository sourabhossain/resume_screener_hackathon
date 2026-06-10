"""
URL configuration for Resume Screening System.
"""
from django.contrib import admin
from django.urls import path, re_path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.shortcuts import render
from django_ratelimit.decorators import ratelimit
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from apps.core.views import serve_protected_media

# Throttle login attempts to blunt credential stuffing / brute force.
# Two layers: per-IP and per-username; block=True returns 403 when exceeded.
_login_view = auth_views.LoginView.as_view(template_name='auth/login.html')
_login_view = ratelimit(key='post:username', rate='5/m', method='POST', block=True)(_login_view)
_login_view = ratelimit(key='ip', rate='10/m', method='POST', block=True)(_login_view)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.core.urls')),
    path('', include('apps.interviews.urls')),

    # API URLs
    path('api/', include('apps.core.api_urls')),

    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Authentication URLs
    path('login/', _login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    # Protected media — requires login; prevents unauthenticated access to PII files
    re_path(r'^media/(?P<path>.+)$', serve_protected_media, name='protected_media'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    from django.views.defaults import page_not_found, server_error
    urlpatterns += [
        path('404/', lambda request: page_not_found(request, None)),
        path('500/', lambda request: server_error(request)),
    ]


# Custom error handlers
def custom_404(request, exception):
    return render(request, '404.html', status=404)

def custom_500(request):
    return render(request, '500.html', status=500)

handler404 = custom_404
handler500 = custom_500