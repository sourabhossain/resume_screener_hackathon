"""The links in outgoing email must be clickable.

Every emailed link is built from SITE_BASE_URL, a plain string somebody types
into a .env file. `localhost:8000` and `careers.sslwireless.com` both look
right there and both pass every other guard, but a mail client reads a link
with no scheme as relative: the button renders, and clicking it does nothing.
Nothing in any log says so -- the recipient simply never answers.
"""
import re

import pytest
from django.core import mail

from apps.core.links import absolute_url, has_scheme, site_base_url

SCHEMELESS = ['localhost:8000', 'careers.sslwireless.com',
              'careers.sslwireless.com/hire', '10.0.0.5:8080']


@pytest.mark.parametrize('base', SCHEMELESS)
def test_a_base_url_without_a_scheme_still_produces_an_absolute_link(settings, base):
    settings.SITE_BASE_URL = base
    url = absolute_url('/verification/abc/')
    assert has_scheme(url), f'{url!r} is relative and cannot be clicked'
    assert url.endswith('/verification/abc/')


@pytest.mark.parametrize('base,expected', [
    ('localhost:8000', 'http://'),
    ('127.0.0.1:8000', 'http://'),
    ('careers.sslwireless.com', 'https://'),
    ('10.0.0.5', 'https://'),
])
def test_only_local_addresses_are_assumed_to_be_plain_http(settings, base, expected):
    settings.SITE_BASE_URL = base
    assert site_base_url().startswith(expected)


@pytest.mark.parametrize('base', [
    'https://careers.sslwireless.com',
    'http://localhost:8000',
    'https://careers.sslwireless.com/',
])
def test_a_base_url_that_already_has_a_scheme_is_left_alone(settings, base):
    settings.SITE_BASE_URL = base
    assert site_base_url() == base.rstrip('/')


def test_an_empty_base_url_is_not_given_a_scheme(settings):
    """It is caught as an Error by the system check; inventing `https://` here
    would turn that into a link to nowhere instead."""
    settings.SITE_BASE_URL = ''
    assert site_base_url() == ''


# ── The checks that catch it before anyone clicks ────────────────────────
def _run_site_check():
    from apps.employee_form.checks import check_site_base_url
    return [m.id for m in check_site_base_url(None)]


def test_a_missing_scheme_is_reported_by_manage_py_check(settings):
    settings.SITE_BASE_URL = 'careers.sslwireless.com'
    assert 'employee_form.W003' in _run_site_check()


def test_a_full_url_reports_nothing(settings):
    settings.DEBUG = False
    settings.SITE_BASE_URL = 'https://careers.sslwireless.com'
    assert _run_site_check() == []


SMTP = 'django.core.mail.backends.smtp.EmailBackend'
CONSOLE = 'django.core.mail.backends.console.EmailBackend'


def test_sending_real_email_with_a_local_link_is_reported(settings):
    """A link to localhost is a link to the *recipient's* machine. Delivering
    that to a real inbox produces a button nobody but the developer can use,
    which is exactly how this went unnoticed."""
    settings.DEBUG = True
    settings.SITE_BASE_URL = 'http://localhost:8000'
    settings.EMAIL_BACKEND = SMTP
    assert 'employee_form.W004' in _run_site_check()


def test_a_local_link_is_fine_when_nothing_is_actually_delivered(settings):
    settings.DEBUG = True
    settings.SITE_BASE_URL = 'http://localhost:8000'
    settings.EMAIL_BACKEND = CONSOLE
    assert 'employee_form.W004' not in _run_site_check()


def test_a_reachable_address_with_real_email_is_fine(settings):
    settings.DEBUG = True
    settings.SITE_BASE_URL = 'https://careers.sslwireless.com'
    settings.EMAIL_BACKEND = SMTP
    assert 'employee_form.W004' not in _run_site_check()


@pytest.mark.parametrize('base,local', [
    ('http://localhost:8000', True),
    ('localhost:8000', True),
    ('https://127.0.0.1', True),
    ('https://careers.sslwireless.com', False),
    # The substring test this replaced called these local, because the words
    # appear inside the hostname.
    ('https://localhost.sslwireless.com', False),
    ('https://my-127.0.0.1-host.com', False),
])
def test_only_a_genuinely_local_host_counts_as_local(base, local):
    from apps.core.links import is_local
    assert is_local(base) is local


# ── End to end: what actually lands in the recipient's inbox ─────────────
HREF = re.compile(r'href="([^"]+)"')


def _button_hrefs(message):
    """Every link in the HTML part. Django stores alternatives as
    (content, mimetype) pairs, not the other way round."""
    html = next((content for content, mimetype in (message.alternatives or [])
                 if mimetype == 'text/html'), '')
    assert html, 'the message has no HTML part'
    hrefs = HREF.findall(html)
    assert hrefs, 'the HTML email has no link at all'
    return hrefs


@pytest.mark.django_db
def test_every_link_in_a_verification_request_is_absolute(settings, sample_job):
    from apps.core.models import Resume
    from apps.reference_checks import services
    from apps.reference_checks.models import ReferenceCheck

    settings.SITE_BASE_URL = 'careers.sslwireless.com'      # the broken shape
    resume = Resume.objects.create(job=sample_job, candidate_name='Ayesha Rahman',
                                   email='ayesha@example.com')
    check = ReferenceCheck.objects.create(
        resume=resume, kind='employer', source_key='employer_1',
        recipient_name='Acme HR', recipient_email='hr@acme.com')

    services.send_request(check, otp='123456')

    message = mail.outbox[-1]
    for href in _button_hrefs(message):
        assert has_scheme(href), f'dead button: href={href!r}'
    # the plain-text part carries the same link for clients that strip HTML
    assert 'https://careers.sslwireless.com/verification/' in message.body


@pytest.mark.django_db
def test_every_link_in_a_candidate_invitation_is_absolute(settings, sample_job):
    from apps.core.models import Resume
    from apps.employee_form import services
    from apps.employee_form.models import EmployeeForm

    settings.SITE_BASE_URL = 'careers.sslwireless.com'
    resume = Resume.objects.create(job=sample_job, candidate_name='Ayesha Rahman',
                                   email='ayesha@example.com')
    form = EmployeeForm.objects.create(resume=resume)

    services.send_invite(form, otp='123456')

    message = mail.outbox[-1]
    for href in _button_hrefs(message):
        assert has_scheme(href), f'dead button: href={href!r}'
    assert 'https://careers.sslwireless.com/information-form/' in message.body
