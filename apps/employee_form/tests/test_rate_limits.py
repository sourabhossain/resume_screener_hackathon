"""The OTP endpoints are rate-limited per form, not per IP.

Bangladeshi mobile carriers NAT many subscribers behind one address, so an
IP-keyed limit locked out honest candidates once earlier ones had used their
attempts. These tests pin that down.
"""
import re
import pytest
from django.core import mail
from django.urls import reverse

from apps.core.models import Resume
from apps.employee_form.models import EmployeeForm
from apps.employee_form.services import issue_invite


@pytest.fixture(autouse=True)
def _keep_cache():
    """Opt out of the project-wide cache clear so rate limits can accumulate."""
    yield


@pytest.fixture
def people(db, sample_job):
    return [
        Resume.objects.create(job=sample_job, candidate_name=f'C{i}',
                              email=f'c{i}@example.com', final_score=60)
        for i in range(6)
    ]


def test_shared_ip_does_not_block_later_candidates(client, people):
    """Six candidates behind one NAT IP each use their 5 OTP attempts."""
    blocked_at = None
    for index, person in enumerate(people):
        form = issue_invite(person)
        url = reverse('employee_form:verify', kwargs={'token': form.token})
        for _ in range(EmployeeForm.OTP_MAX_ATTEMPTS):
            resp = client.post(url, {'code': '000000'})
            if resp.status_code == 429:
                blocked_at = index
                break
        if blocked_at is not None:
            break

    assert blocked_at is None, (
        f'candidate #{blocked_at + 1} on a shared IP got HTTP 429 before '
        'using their own attempts'
    )


def test_correct_code_still_works_after_others_used_the_ip(client, people):
    """The real risk: an honest candidate blocked by strangers on the same IP."""
    for person in people[:-1]:
        form = issue_invite(person)
        url = reverse('employee_form:verify', kwargs={'token': form.token})
        for _ in range(EmployeeForm.OTP_MAX_ATTEMPTS):
            client.post(url, {'code': '000000'})

    victim = issue_invite(people[-1])
    otp = re.search(r'code is:\s*(\d{6})', mail.outbox[-1].body).group(1)
    resp = client.post(
        reverse('employee_form:verify', kwargs={'token': victim.token}),
        {'code': otp})

    assert resp.status_code != 429, 'honest candidate blocked by a shared IP'
    assert resp.status_code == 302, f'correct code did not open the form ({resp.status_code})'
