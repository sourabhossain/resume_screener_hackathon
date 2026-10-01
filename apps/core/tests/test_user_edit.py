"""Editing a staff account: details, access, and the guards against lock-out."""
import pytest
from django.urls import reverse


@pytest.fixture
def admin(db, django_user_model, client):
    user = django_user_model.objects.create_superuser('boss', 'boss@sslwireless.com', 'pw12345!')
    client.login(username='boss', password='pw12345!')
    return user


@pytest.fixture
def member(db, django_user_model):
    return django_user_model.objects.create_user('rina', 'rina@sslwireless.com', 'x')


def _edit(client, user, **data):
    payload = {'username': user.username, 'first_name': user.first_name, 'last_name': user.last_name,
               'email': user.email, **data}
    for flag in ('is_staff', 'is_superuser'):
        if payload.get(flag) is False:
            payload.pop(flag)
    return client.post(reverse('core:user_edit', kwargs={'pk': user.pk}), payload)


@pytest.mark.django_db
def test_a_superuser_can_change_a_name_email_and_hr_access(client, admin, member):
    response = _edit(client, member, first_name='Rina', last_name='Akter', email='rina.akter@sslwireless.com',
                     is_staff='on')

    member.refresh_from_db()
    assert response.status_code == 302
    assert (member.get_full_name(), member.email, member.is_staff) == ('Rina Akter', 'rina.akter@sslwireless.com', True)


@pytest.mark.django_db
def test_two_accounts_cannot_share_an_email(client, admin, member):
    response = _edit(client, member, email='BOSS@sslwireless.com')

    member.refresh_from_db()
    assert response.status_code == 200 and member.email == 'rina@sslwireless.com'


@pytest.mark.django_db
def test_a_taken_username_is_refused(client, admin, member):
    _edit(client, member, username='boss')
    member.refresh_from_db()
    assert member.username == 'rina'


@pytest.mark.django_db
def test_you_cannot_remove_your_own_superuser_access(client, admin):
    _edit(client, admin, is_superuser=False)
    admin.refresh_from_db()
    assert admin.is_superuser


@pytest.mark.django_db
def test_another_superuser_can_be_made_an_ordinary_user(client, admin, django_user_model):
    other = django_user_model.objects.create_superuser('second', 's@sslwireless.com', 'x')

    _edit(client, other, is_superuser=False)

    other.refresh_from_db()
    assert not other.is_superuser


@pytest.mark.django_db
def test_only_a_superuser_can_edit_accounts(client, django_user_model, member):
    django_user_model.objects.create_user('hr', 'hr@sslwireless.com', 'pw12345!', is_staff=True)
    client.login(username='hr', password='pw12345!')

    _edit(client, member, first_name='Hacked')

    member.refresh_from_db()
    assert member.first_name == ''


@pytest.mark.django_db
def test_the_user_list_offers_edit(client, admin, member):
    html = client.get(reverse('core:user_list')).content.decode()
    assert reverse('core:user_edit', kwargs={'pk': member.pk}) in html and 'Edit details' in html
