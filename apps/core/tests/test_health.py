"""Tests for the deep /health/ endpoint (db + redis + celery)."""
import importlib
from unittest.mock import patch

import pytest
from django.urls import reverse

# NB: apps.core.views re-exports `dashboard` (the view fn), which shadows the
# submodule attribute — import the module explicitly so monkeypatching the
# module-level probes affects health_check's global lookups.
dashboard = importlib.import_module('apps.core.views.dashboard')


HEALTH_URL = reverse('core:health_check')


@pytest.mark.django_db
class TestHealthCheck:
    def test_all_healthy_returns_200(self, client, monkeypatch):
        monkeypatch.setattr(dashboard, '_probe_redis', lambda: True)
        monkeypatch.setattr(dashboard, '_probe_celery', lambda: True)
        resp = client.get(HEALTH_URL)
        assert resp.status_code == 200
        body = resp.json()
        assert body['status'] == 'ok'
        assert body['components'] == {
            'db': {'ok': True}, 'redis': {'ok': True}, 'celery': {'ok': True},
        }

    def test_requires_no_auth(self, client, monkeypatch):
        # No login: must not redirect to the login page.
        monkeypatch.setattr(dashboard, '_probe_redis', lambda: True)
        monkeypatch.setattr(dashboard, '_probe_celery', lambda: True)
        resp = client.get(HEALTH_URL)
        assert resp.status_code == 200  # not a 302 -> login

    def test_redis_down_returns_503_degraded(self, client, monkeypatch):
        monkeypatch.setattr(dashboard, '_probe_redis', lambda: False)
        monkeypatch.setattr(dashboard, '_probe_celery', lambda: True)
        resp = client.get(HEALTH_URL)
        assert resp.status_code == 503
        body = resp.json()
        assert body['status'] == 'degraded'          # db up, so degraded not unhealthy
        assert body['components']['db']['ok'] is True
        assert body['components']['redis'] == {'ok': False, 'reason': 'unreachable'}

    def test_celery_down_returns_503_degraded(self, client, monkeypatch):
        monkeypatch.setattr(dashboard, '_probe_redis', lambda: True)
        monkeypatch.setattr(dashboard, '_probe_celery', lambda: False)
        resp = client.get(HEALTH_URL)
        assert resp.status_code == 503
        body = resp.json()
        assert body['status'] == 'degraded'
        assert body['components']['celery'] == {'ok': False, 'reason': 'unreachable'}

    def test_db_down_returns_503_unhealthy(self, client, monkeypatch):
        monkeypatch.setattr(dashboard, '_probe_db', lambda: False)
        monkeypatch.setattr(dashboard, '_probe_redis', lambda: True)
        monkeypatch.setattr(dashboard, '_probe_celery', lambda: True)
        resp = client.get(HEALTH_URL)
        assert resp.status_code == 503
        assert resp.json()['status'] == 'unhealthy'

    def test_payload_leaks_no_secrets_or_hostnames(self, client, monkeypatch):
        monkeypatch.setattr(dashboard, '_probe_redis', lambda: False)
        monkeypatch.setattr(dashboard, '_probe_celery', lambda: False)
        raw = client.get(HEALTH_URL).content.decode().lower()
        for leak in ('redis://', 'localhost', '6379', 'password', 'amqp', '@', 'host'):
            assert leak not in raw, f'health payload leaked {leak!r}'
        # Only name -> {ok[, reason]} is exposed.
        for comp in client.get(HEALTH_URL).json()['components'].values():
            assert set(comp).issubset({'ok', 'reason'})

    def test_celery_ping_uses_short_timeout(self, monkeypatch):
        """Timeout is verified by asserting the arg passed to the broker ping
        (mock-based), not by a real sleep."""
        import config.celery as celery_mod
        with patch.object(celery_mod.app.control, 'ping', return_value=[{'w': 'pong'}]) as mock_ping:
            assert dashboard._celery_ping() is True
            mock_ping.assert_called_once_with(timeout=dashboard.CELERY_PING_TIMEOUT)
        assert dashboard.CELERY_PING_TIMEOUT <= 2.0

    def test_celery_probe_is_cached(self, monkeypatch):
        """The heavy broker ping is cached, so repeated polls don't re-broadcast."""
        calls = []
        monkeypatch.setattr(dashboard, '_celery_ping', lambda: calls.append(1) or True)
        assert dashboard._probe_celery() is True
        assert dashboard._probe_celery() is True
        assert len(calls) == 1  # second call served from cache
