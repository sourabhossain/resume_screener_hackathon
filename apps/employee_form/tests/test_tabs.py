"""The section tabs: what can be opened, what is locked, and what is current."""
import re

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Resume
from apps.employee_form import views
from apps.employee_form.models import EmployeeForm


@pytest.fixture
def form(db, sample_job):
    resume = Resume.objects.create(job=sample_job, candidate_name='Tab Case', email='tab@example.com')
    return EmployeeForm.objects.create(resume=resume, otp_verified_at=timezone.now(), current_step='employment')


@pytest.fixture
def verified(client, form):
    session = client.session
    session[views._session_key(form)] = True
    session.save()
    return client


def _page(client, form, step_key):
    return client.get(reverse('employee_form:step', kwargs={'token': form.token, 'step_key': step_key}))


def _url(form, step_key):
    return reverse('employee_form:step', kwargs={'token': form.token, 'step_key': step_key})


@pytest.mark.django_db
def test_sections_reached_are_links_and_later_ones_are_locked(verified, form):
    html = _page(verified, form, 'section_a').content.decode()
    nav = html[html.index('aria-label="Form sections"'):html.index('</nav>', html.index('aria-label="Form sections"'))]

    assert f'href="{_url(form, "section_b")}"' in nav
    assert f'href="{_url(form, "employment")}"' in nav
    assert f'href="{_url(form, "reference_1")}"' not in nav
    assert 'aria-disabled="true"' in nav and 'Reference 1' in nav


@pytest.mark.django_db
def test_the_open_section_is_marked_current_and_finished_ones_carry_a_tick(verified, form):
    html = _page(verified, form, 'section_b').content.decode()

    current = re.search(r'<a [^>]*aria-current="step"[^>]*>', html).group(0)
    assert _url(form, 'section_b') in current
    assert html.count(', completed</span>') == 1


@pytest.mark.django_db
def test_every_tab_on_offer_is_a_section_the_server_will_open(verified, form):
    tabs = views._section_tabs(form, 'section_a')
    for tab in tabs:
        response = _page(verified, form, tab['key'])
        opens = response.status_code == 200
        assert opens == (tab['state'] != 'locked'), tab
