"""Absolute links for email, where there is no request to build them from.

Both the candidate invitation and the external verification request are sent
from Celery tasks, so neither can call `request.build_absolute_uri()`. They
build links from SITE_BASE_URL instead, and that setting is a plain string
somebody types into a .env file.
"""
from django.conf import settings

# Kept in step with employee_form.checks.LOCAL_HOSTS, which warns about these
# being used in production.
LOCAL_HOSTS = frozenset({'localhost', '127.0.0.1', '0.0.0.0', '::1'})


def has_scheme(base: str) -> bool:
    return '://' in base


def host_of(base: str) -> str:
    """The bare hostname, whether or not a scheme or port is present."""
    without_scheme = base.split('://', 1)[-1]
    return without_scheme.split('/', 1)[0].split(':', 1)[0].strip().lower()


def is_local(base: str) -> bool:
    """Whether this address only resolves on the machine running the server."""
    return host_of(base) in LOCAL_HOSTS


def site_base_url() -> str:
    """SITE_BASE_URL, guaranteed to carry a scheme.

    `careers.sslwireless.com` looks perfectly reasonable in a .env, and every
    other check passes it. What it produces is `href="careers.sslwireless.com/
    verification/..."`, which a mail client reads as a relative path and cannot
    open -- the button is simply dead, in every email, with nothing in any log.

    Local addresses get http and everything else https: a public careers site
    served over plain HTTP is not a case worth guessing for, and the form
    carries NID numbers and ID scans.
    """
    base = (getattr(settings, 'SITE_BASE_URL', '') or '').strip().rstrip('/')
    if not base or has_scheme(base):
        return base

    scheme = 'http' if is_local(base) else 'https'
    return f'{scheme}://{base}'


def absolute_url(path: str) -> str:
    """Join an app path onto the site's base URL."""
    return f'{site_base_url()}{path}'
