"""
URL configuration for Resume Screening System.
"""
import logging
from django.contrib import admin
from django.urls import path, re_path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from apps.core.views import ToastLoginView
from django.core.cache import caches
from django.http import HttpResponse
from django.shortcuts import render
from django_ratelimit.decorators import ratelimit
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from apps.core.views import serve_protected_media

logger = logging.getLogger(__name__)


def _auth_cache_required(view_fn):
    """Fail closed on POST when the rate-limit cache is unreachable.
    Non-auth views keep the global fail-open default (RATELIMIT_FAIL_OPEN=True);
    only the login endpoint uses this wrapper."""
    def wrapper(request, *args, **kwargs):
        if request.method == 'POST':
            rl_cache_name = getattr(settings, 'RATELIMIT_USE_CACHE', 'default')
            rl_cache = caches[rl_cache_name]
            if hasattr(rl_cache, 'is_available') and not rl_cache.is_available():
                logger.warning(
                    "auth.rate_limit: login POST blocked, cache '%s' unreachable",
                    rl_cache_name,
                )
                response = HttpResponse(
                    'Service temporarily unavailable. Please try again later.',
                    status=503,
                )
                response['Retry-After'] = '60'
                return response
        return view_fn(request, *args, **kwargs)
    wrapper.__name__ = view_fn.__name__
    return wrapper


# Throttle login: two layers (per-username + per-IP); fail closed if cache unreachable.
_login_view = ToastLoginView.as_view()
_login_view = ratelimit(key='post:username', rate='5/m', method='POST', block=True)(_login_view)
_login_view = ratelimit(key='ip', rate='10/m', method='POST', block=True)(_login_view)
_login_view = _auth_cache_required(_login_view)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.core.urls')),
    path('', include('apps.interviews.urls')),

    # API URLs
    path('api/', include('apps.core.api_urls')),

    # API Documentation — login required; schema exposes model structure that aids enumeration attacks.
    path('api/schema/', SpectacularAPIView.as_view(permission_classes=[IsAuthenticated]), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[IsAuthenticated]), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema', permission_classes=[IsAuthenticated]), name='redoc'),

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
def custom_403(request, exception=None):
    return render(request, '403.html', status=403)

def custom_404(request, exception):
    return render(request, '404.html', status=404)

def custom_500(request):
    return render(request, '500.html', status=500)

handler403 = custom_403
handler404 = custom_404
handler500 = custom_500