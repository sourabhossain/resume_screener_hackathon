import logging
import uuid

logger = logging.getLogger(__name__)

class RequestCorrelationMiddleware:
    """Tags every request with a short ID so web and Celery logs can be correlated."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())[:8]
        request.request_id = request_id
        response = self.get_response(request)
        response['X-Request-ID'] = request_id
        return response

class ContentSecurityPolicyMiddleware:
    """Emits a Content-Security-Policy header on every response.

    Allows the CDNs already referenced in base.html (htmx via unpkg,
    AlpineJS and SweetAlert2 via jsdelivr, Google Fonts) while blocking
    inline frames and object embeds. 'unsafe-inline' is required because
    AlpineJS (x-data/x-show) and inline <script> blocks in base.html
    cannot use nonces without template-level changes.
    """

    _CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none';"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if 'Content-Security-Policy' not in response:
            response['Content-Security-Policy'] = self._CSP
        return response
