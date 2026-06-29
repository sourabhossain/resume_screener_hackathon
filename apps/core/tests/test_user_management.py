"""
Tests for user-management views (superuser-only).

Covers:
- Non-superuser (regular recruiter) cannot access any user-management route
- Superuser can list, create, change passwords, and toggle active status
- Self-deactivation guard
"""
import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()

@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(
        username='admin', password='AdminPass1!', email='admin@example.com'
    )

@pytest.fixture
def superuser_client(client, superuser):
    client.force_login(superuser)
    return client

@pytest.fixture
def regular_user(db):
    return User.objects.create_user(username='recruiter', password='pass')

@pytest.fixture
def regular_client(client, regular_user):
    client.force_login(regular_user)
    return client

@pytest.mark.django_db
class TestUserManagementAccessControl:

    def test_unauthenticated_user_list_redirects(self, client):
        resp = client.get(reverse('core:user_list'))
        assert resp.status_code == 302
        assert 'login' in resp['Location']

    def test_regular_user_list_redirects_to_dashboard(self, regular_client):
        resp = regular_client.get(reverse('core:user_list'))
        assert resp.status_code == 302

    def test_regular_user_create_redirects(self, regular_client):
        resp = regular_client.get(reverse('core:user_create'))
        assert resp.status_code == 302

    def test_regular_user_cannot_change_password(self, regular_client, superuser):
        resp = regular_client.get(
            reverse('core:user_change_password', kwargs={'pk': superuser.pk})
        )
        assert resp.status_code == 302

    def test_regular_user_cannot_toggle_active(self, regular_client, superuser):
        resp = regular_client.post(
            reverse('core:user_toggle_active', kwargs={'pk': superuser.pk})
        )
        assert resp.status_code == 302
        superuser.refresh_from_db()
        assert superuser.is_active is True

    def test_superuser_can_access_user_list(self, superuser_client):
        resp = superuser_client.get(reverse('core:user_list'))
        assert resp.status_code == 200

    def test_superuser_can_access_user_create(self, superuser_client):
        resp = superuser_client.get(reverse('core:user_create'))
        assert resp.status_code == 200

@pytest.mark.django_db
class TestUserCreate:

    def test_create_basic_user(self, superuser_client):
        resp = superuser_client.post(reverse('core:user_create'), {
            'username': 'newrecruiter',
            'password1': 'StrongPass1!',
            'password2': 'StrongPass1!',
            'email': 'newrecruiter@example.com',
        })
        assert resp.status_code == 302
        assert User.objects.filter(username='newrecruiter').exists()

    def test_created_user_is_not_superuser_by_default(self, superuser_client):
        superuser_client.post(reverse('core:user_create'), {
            'username': 'plainuser',
            'password1': 'StrongPass1!',
            'password2': 'StrongPass1!',
        })
        u = User.objects.get(username='plainuser')
        assert u.is_superuser is False

    def test_create_superuser_with_flag(self, superuser_client):
        superuser_client.post(reverse('core:user_create'), {
            'username': 'newadmin',
            'password1': 'StrongPass1!',
            'password2': 'StrongPass1!',
            'is_superuser': 'on',
        })
        u = User.objects.get(username='newadmin')
        assert u.is_superuser is True

    def test_mismatched_passwords_rejected(self, superuser_client):
        resp = superuser_client.post(reverse('core:user_create'), {
            'username': 'baduser',
            'password1': 'StrongPass1!',
            'password2': 'DifferentPass1!',
        })
        assert resp.status_code == 200
        assert not User.objects.filter(username='baduser').exists()

@pytest.mark.django_db
class TestUserPasswordChange:

    def test_superuser_can_change_target_password(self, superuser_client, regular_user):
        resp = superuser_client.post(
            reverse('core:user_change_password', kwargs={'pk': regular_user.pk}),
            {'new_password1': 'NewStrongPass1!', 'new_password2': 'NewStrongPass1!'},
        )
        assert resp.status_code == 302
        regular_user.refresh_from_db()
        assert regular_user.check_password('NewStrongPass1!')

    def test_password_change_form_renders(self, superuser_client, regular_user):
        resp = superuser_client.get(
            reverse('core:user_change_password', kwargs={'pk': regular_user.pk})
        )
        assert resp.status_code == 200
        assert 'form' in resp.context

@pytest.mark.django_db
class TestUserToggleActive:

    def test_superuser_deactivates_user(self, superuser_client, regular_user):
        superuser_client.post(
            reverse('core:user_toggle_active', kwargs={'pk': regular_user.pk})
        )
        regular_user.refresh_from_db()
        assert regular_user.is_active is False

    def test_superuser_reactivates_user(self, superuser_client, regular_user):
        regular_user.is_active = False
        regular_user.save()
        superuser_client.post(
            reverse('core:user_toggle_active', kwargs={'pk': regular_user.pk})
        )
        regular_user.refresh_from_db()
        assert regular_user.is_active is True

    def test_superuser_cannot_deactivate_self(self, superuser_client, superuser):
        superuser_client.post(
            reverse('core:user_toggle_active', kwargs={'pk': superuser.pk})
        )
        superuser.refresh_from_db()
        assert superuser.is_active is True

    def test_toggle_requires_post(self, superuser_client, regular_user):
        """GET to toggle endpoint does nothing (no side-effect on safe method)."""
        superuser_client.get(
            reverse('core:user_toggle_active', kwargs={'pk': regular_user.pk})
        )
        regular_user.refresh_from_db()
        assert regular_user.is_active is True
