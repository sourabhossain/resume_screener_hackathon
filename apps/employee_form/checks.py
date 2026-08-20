"""Deploy-time guards for the settings this app depends on.

These run with `manage.py check` (and on every start), so a misconfiguration that
would only show up as a broken candidate email is caught before traffic reaches
it. Each one here has already gone wrong once during development.
"""
from django.conf import settings
from django.core.checks import Error, Warning, register

LOCAL_HOSTS = ('localhost', '127.0.0.1', '0.0.0.0', '::1')


@register()
def check_site_base_url(app_configs, **kwargs):
    """The emailed form link is built from SITE_BASE_URL, not from a request.

    Left at its local default in production, every invitation would carry a
    link the candidate cannot open -- and nothing else would look wrong.
    """
    errors = []
    base = (getattr(settings, 'SITE_BASE_URL', '') or '').strip()

    if not base:
        errors.append(Error(
            'SITE_BASE_URL is empty, so candidate form links cannot be built.',
            hint='Set SITE_BASE_URL to the address candidates reach, '
                 'e.g. https://careers.sslwireless.com',
            id='employee_form.E001',
        ))
        return errors

    if not settings.DEBUG and any(host in base for host in LOCAL_HOSTS):
        errors.append(Error(
            f'SITE_BASE_URL is {base!r} with DEBUG off. Every emailed form '
            'link would point at the server itself.',
            hint='Set SITE_BASE_URL to the public careers address.',
            id='employee_form.E002',
        ))

    if not settings.DEBUG and base.startswith('http://'):
        errors.append(Warning(
            f'SITE_BASE_URL is {base!r} — candidate links would be plain HTTP. '
            'The form carries NID numbers and ID scans.',
            hint='Use https:// for the public address.',
            id='employee_form.W001',
        ))
    return errors


@register()
def check_email_delivery(app_configs, **kwargs):
    """Catch the two SMTP misconfigurations that already broke invitations."""
    errors = []
    backend = getattr(settings, 'EMAIL_BACKEND', '')
    if 'smtp' not in backend:
        # Console/locmem backends need nothing else; nothing is delivered.
        return errors

    if not getattr(settings, 'EMAIL_HOST', ''):
        errors.append(Error(
            'EMAIL_BACKEND is SMTP but EMAIL_HOST is empty, so invitations '
            'cannot be sent.',
            hint='Set EMAIL_HOST (Microsoft 365 tenants use smtp.office365.com). '
                 'Note that smtp.sslwireless.com resolves to 127.0.0.1 and is '
                 'not reachable.',
            id='employee_form.E003',
        ))

    user = (getattr(settings, 'EMAIL_HOST_USER', '') or '').strip().lower()
    sender = (getattr(settings, 'DEFAULT_FROM_EMAIL', '') or '').strip().lower()
    if user and sender and user not in sender:
        errors.append(Warning(
            f'DEFAULT_FROM_EMAIL ({sender!r}) is not the authenticated mailbox '
            f'({user!r}).',
            hint='Microsoft 365 rejects a mismatched sender with '
                 '"554 5.2.252 SendAsDenied" unless that mailbox has Send As '
                 'permission on the address.',
            id='employee_form.W002',
        ))
    return errors
