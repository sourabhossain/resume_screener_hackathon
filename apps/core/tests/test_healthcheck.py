"""The container healthcheck must be able to reach /health/.

It failed in production for five days straight while the site served traffic
normally: SECURE_SSL_REDIRECT sent the probe's plain-HTTP request to https,
gunicorn does not speak TLS, and the probe hung on the handshake. A red health
label that nobody can act on also hides a real outage when one happens.
"""
import json

import pytest
from django.conf import settings
from django.http import HttpResponse
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory, override_settings


def test_health_is_exempt_from_the_https_redirect():
    assert any('health' in pattern for pattern in settings.SECURE_REDIRECT_EXEMPT)


@override_settings(SECURE_SSL_REDIRECT=True)
def test_the_probe_is_not_redirected():
    """Built inside the override: SecurityMiddleware reads settings at init."""
    middleware = SecurityMiddleware(lambda request: HttpResponse('ok'))
    response = middleware(RequestFactory().get('/health/'))

    assert response.status_code == 200, 'the probe would follow a 301 into a TLS handshake'


@override_settings(SECURE_SSL_REDIRECT=True)
def test_ordinary_pages_are_still_redirected():
    """Guards the exemption from being widened by accident."""
    middleware = SecurityMiddleware(lambda request: HttpResponse('ok'))

    for path in ('/', '/jobs/', '/careers/', '/health/extra/'):
        response = middleware(RequestFactory().get(path))
        assert response.status_code == 301, path
        assert response['Location'].startswith('https://'), path


@pytest.mark.django_db
def test_health_answers_what_the_probe_checks(client):
    """The probe asserts status==200 and status=='healthy'."""
    response = client.get('/health/')

    assert response.status_code == 200
    assert json.loads(response.content)['status'] == 'healthy'
