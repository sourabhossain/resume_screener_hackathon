import logging
import uuid

from django.middleware.gzip import GZipMiddleware

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

    Scripts come only from this site (htmx, AlpineJS and SweetAlert2 are
    served from static/js/vendor); Google Fonts is the one outside origin.
    Inline frames and object embeds are blocked. 'unsafe-inline' is required because
    AlpineJS (x-data/x-show) and inline <script> blocks in base.html
    cannot use nonces without template-level changes.
    """

    _CSP = (
        "default-src 'self'; "
        # 'unsafe-eval' is required by AlpineJS v3: it uses the Function()
        # constructor internally to evaluate x-data/x-show/x-text expressions.
        # Without it, Alpine silently drops all bindings (blank buttons, empty
        # dropdowns, wrong visibility states).
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
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


class TextGZipMiddleware(GZipMiddleware):
    """Gzips pages and JSON; files and archives go out untouched.

    A pipeline page repeats the same row markup dozens of times and shrinks
    about twentyfold. PDFs, ZIPs and spreadsheets are already compressed, and
    gzipping a download would only drop its Content-Length. Django's own
    middleware pads every response against BREACH (Heal The Breach).
    """

    _COMPRESSIBLE = ('text/', 'application/json', 'application/javascript')

    def process_response(self, request, response):
        if not response.get('Content-Type', '').startswith(self._COMPRESSIBLE):
            return response
        return super().process_response(request, response)
