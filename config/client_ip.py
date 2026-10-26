"""The visitor's address for rate limiting, when the app sits behind a proxy.

Behind a proxy every request arrives from the proxy, so keying limits on
REMOTE_ADDR turns each per-visitor limit into one limit for the whole site.
CLIENT_IP_HEADER names the header the proxy overwrites with the real address
(nginx: ``proxy_set_header X-Real-IP $remote_addr;`` gives HTTP_X_REAL_IP).
Apache's mod_proxy sends X-Forwarded-For instead and appends the address it
saw last, so the last entry of that header is the fallback.
Only trust either when the app port is reachable from the proxy alone;
otherwise anyone could send the header and pick their own address.
"""
from django.conf import settings


def client_ip(request) -> str:
    header = getattr(settings, 'CLIENT_IP_HEADER', '')
    if header:
        for name in (header, 'HTTP_X_FORWARDED_FOR'):
            value = (request.META.get(name) or '').split(',')[-1].strip()
            if value:
                return value
    return request.META.get('REMOTE_ADDR', '')
