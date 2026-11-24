"""Every dropdown is the shared picker, wrapped around a native select that stays the posted value."""
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Resume
from apps.employee_form import views as eif_views
from apps.employee_form.models import EmployeeForm

TEMPLATES = Path(settings.BASE_DIR) / 'templates'


def _selects_outside_a_picker(html):
    """Native selects not inside a .select-picker wrapper (the page's own dropdowns are all wrapped)."""
    bare = []
    for match in re.finditer(r'<select\b[^>]*name="([^"]+)"', html):
        before = html[:match.start()]
        opened = before.rfind('class="select-picker"') if 'class="select-picker"' in before else -1
        opened = max(opened, before.rfind('select-picker" x-data="selectPicker()"'))
        if opened == -1 or '</select>' in before[opened:]:
            bare.append(match.group(1))
    return bare


def test_no_template_writes_a_bare_select():
    for path in TEMPLATES.rglob('*.html'):
        text = path.read_text()
        for match in re.finditer(r'<select\b', text):
            context = text[max(0, match.start() - 400):match.start()]
            assert 'selectPicker()' in context, f'{path.relative_to(TEMPLATES)} has a <select> outside the picker'


@pytest.fixture
def eif(db, sample_job):
    resume = Resume.objects.create(job=sample_job, candidate_name='Picker Case', email='picker@example.com')
    return EmployeeForm.objects.create(resume=resume, otp_verified_at=timezone.now(), current_step='d7_declaration')


@pytest.mark.django_db
@pytest.mark.parametrize('step', ['section_b', 'employment', 'department', 'reference_1'])
def test_information_form_selects_use_the_picker(client, eif, step):
    session = client.session
    session[eif_views._session_key(eif)] = True
    session.save()
    html = client.get(reverse('employee_form:step', kwargs={'token': eif.token, 'step_key': step})).content.decode()
    names = re.findall(r'<select\b[^>]*name="([^"]+)"', html)
    assert names, f'{step} should ask at least one select question'
    assert html.count('x-data="selectPicker()"') == len(names)
    assert _selects_outside_a_picker(html) == []
    assert html.count('class="form-input select-picker__trigger"') == len(names)


@pytest.mark.django_db
def test_the_department_select_keeps_its_id_for_the_role_fields_trigger(client, eif):
    session = client.session
    session[eif_views._session_key(eif)] = True
    session.save()
    html = client.get(reverse('employee_form:step', kwargs={'token': eif.token, 'step_key': 'department'})).content.decode()
    trigger = re.search(r'hx-trigger="change from:#(id_\w+)"', html).group(1)
    assert f'id="{trigger}"' in html and html.index(f'id="{trigger}"') > html.index('x-data="selectPicker()"')
