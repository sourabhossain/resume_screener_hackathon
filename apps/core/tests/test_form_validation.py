"""Tests for shared form field validation."""
import pytest
from django import forms

from apps.core.form_utils import clean_label_text, clean_person_text, clean_phone_text
from apps.core.forms import JobForm, ResumeForm, ResumeEditForm
from apps.interviews.forms import InterviewerAddForm


class TestCleanPersonText:
    def test_bengali_name(self):
        assert clean_person_text('আসাদ হোসেন') == 'আসাদ হোসেন'

    def test_rejects_special_chars(self):
        with pytest.raises(forms.ValidationError):
            clean_person_text('bad@name', required=True)

    def test_requires_letter(self):
        with pytest.raises(forms.ValidationError):
            clean_person_text('12345', required=True)


class TestCleanLabelText:
    def test_allows_ampersand_and_slash(self):
        assert clean_label_text('R&D / Engineering') == 'R&D / Engineering'

    def test_rejects_at_sign(self):
        with pytest.raises(forms.ValidationError):
            clean_label_text('bad@title', required=True)


class TestCleanPhoneText:
    def test_valid_bangladesh_number(self):
        assert clean_phone_text('+880 1711-123456', required=True) == '+880 1711-123456'

    def test_rejects_letters(self):
        with pytest.raises(forms.ValidationError):
            clean_phone_text('call-me', required=True)

    def test_too_few_digits(self):
        with pytest.raises(forms.ValidationError):
            clean_phone_text('123', required=True)


@pytest.mark.django_db
class TestResumeFormValidation:
    def test_rejects_invalid_candidate_name(self):
        form = ResumeForm({'candidate_name': '##!#!', 'email': '', 'phone': ''})
        assert not form.is_valid()
        assert 'candidate_name' in form.errors

    def test_require_contact_blocks_empty_email(self):
        form = ResumeForm(
            {'candidate_name': 'Karim Hossain', 'email': '', 'phone': '+8801711123456'},
            require_contact=True,
        )
        assert not form.is_valid()
        assert 'email' in form.errors


@pytest.mark.django_db
class TestJobFormValidation:
    def test_rejects_invalid_title(self):
        form = JobForm({'title': '@@@', 'description': 'Valid description here.', 'status': 'draft'})
        assert not form.is_valid()
        assert 'title' in form.errors


@pytest.mark.django_db
class TestInterviewerAddFormValidation:
    def test_position_allows_rd_label(self):
        form = InterviewerAddForm({
            'interviewer_name': 'Carol',
            'interviewer_position': 'R&D Lead',
            'interviewer_department': 'Engineering',
        })
        assert form.is_valid(), form.errors
