"""The visitor's address for rate limiting, when the app sits behind a proxy.

Behind nginx every request arrives from the proxy, so keying limits on
REMOTE_ADDR turns each per-visitor limit into one limit for the whole site.
CLIENT_IP_HEADER names the header the proxy overwrites with the real address
(nginx: ``proxy_set_header X-Real-IP $remote_addr;`` gives HTTP_X_REAL_IP).
Only trust it when the app port is reachable from the proxy alone; otherwise
anyone could send the header and pick their own address.
"""
from django.conf import settings


def client_ip(request) -> str:
    header = getattr(settings, 'CLIENT_IP_HEADER', '')
    if header:
        value = (request.META.get(header) or '').split(',')[-1].strip()
        if value:
            return value
    return request.META.get('REMOTE_ADDR', '')
