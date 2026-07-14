"""Tests for the needs-review resolve flow (resume_resolve_review):
assign a recruiter-chosen job family and re-screen with detection skipped."""
from html.parser import HTMLParser
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.core.models import AuditLog, Resume


def test_every_catalog_family_has_an_explicit_label():
    """A new family added to JOB_FAMILIES without a FAMILY_LABELS entry must
    fail fast rather than silently fall back to a humanized key."""
    from apps.core.services.job_families import JOB_FAMILIES, FAMILY_LABELS, family_choices
    missing = [k for k in JOB_FAMILIES if k not in FAMILY_LABELS]
    assert not missing, f"families missing an explicit label: {missing}"
    # family_choices() must pair every machine value with its explicit label,
    # in catalog order, with no humanized-key fallback.
    choices = family_choices()
    assert [v for v, _ in choices] == list(JOB_FAMILIES)
    for value, label in choices:
        assert label == FAMILY_LABELS[value]
    # The families that used to humanize badly now read correctly.
    labels = dict(choices)
    assert labels['data_ai'] == 'Data & AI'
    assert labels['devops_sre'] == 'DevOps / SRE'
    assert labels['qa_test'] == 'QA & Testing'


def _url(resume):
    return reverse('core:resume_resolve_review', kwargs={'uuid': resume.uuid})


@pytest.mark.django_db
class TestResolveReview:
    def _needs_review(self, resume, reason='Job family uncertain from the description'):
        resume.screening_status = 'needs_review'
        resume.reasoning = reason
        resume.save(update_fields=['screening_status', 'reasoning'])
        return resume

    def test_requires_login(self, client, sample_resume):
        self._needs_review(sample_resume)
        resp = client.post(_url(sample_resume), {'job_type': 'software_engineering'})
        assert resp.status_code == 302
        assert 'login' in resp.url

    def test_resolve_happy_path(self, authenticated_client, sample_resume):
        self._needs_review(sample_resume)
        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            resp = authenticated_client.post(_url(sample_resume), {'job_type': 'software_engineering'})

        assert resp.status_code == 302
        sample_resume.refresh_from_db()
        assert sample_resume.screening_status == 'processing'
        # Task dispatched with the chosen family threaded through.
        mock_delay.assert_called_once_with(sample_resume.id, job_type='software_engineering')
        # Audit row records the chosen family in details.
        row = AuditLog.objects.get(action='resume.rescreen_requested',
                                   entity_id=str(sample_resume.uuid))
        assert 'software_engineering' in row.details

    def test_unknown_family_rejected(self, authenticated_client, sample_resume):
        self._needs_review(sample_resume)
        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            resp = authenticated_client.post(_url(sample_resume), {'job_type': 'not_a_real_family'})

        assert resp.status_code == 302
        sample_resume.refresh_from_db()
        assert sample_resume.screening_status == 'needs_review'   # unchanged
        mock_delay.assert_not_called()
        assert not AuditLog.objects.filter(action='resume.rescreen_requested').exists()

    def test_rejected_when_not_needs_review(self, authenticated_client, sample_resume):
        sample_resume.screening_status = 'completed'
        sample_resume.save(update_fields=['screening_status'])
        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            resp = authenticated_client.post(_url(sample_resume), {'job_type': 'software_engineering'})

        assert resp.status_code == 302
        sample_resume.refresh_from_db()
        assert sample_resume.screening_status == 'completed'      # untouched
        mock_delay.assert_not_called()

    def test_soft_deleted_resume_404(self, authenticated_client, sample_resume):
        self._needs_review(sample_resume)
        sample_resume.soft_delete()
        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            resp = authenticated_client.post(_url(sample_resume), {'job_type': 'software_engineering'})

        assert resp.status_code == 404
        mock_delay.assert_not_called()

    def test_list_shows_resolve_control_and_reason(self, authenticated_client, sample_resume):
        self._needs_review(sample_resume, reason='Ambiguous title spanning two families')
        resp = authenticated_client.get(reverse('core:needs_review'))
        content = resp.content.decode()
        assert _url(sample_resume) in content                     # resolve control posts here
        assert 'Ambiguous title spanning two families' in content  # stored reason shown
        assert 'software_engineering' in content                   # a catalog option value

    def test_dropdown_renders_explicit_labels_not_humanized_keys(self, authenticated_client, sample_resume):
        self._needs_review(sample_resume)
        resp = authenticated_client.get(reverse('core:needs_review'))
        content = resp.content.decode()
        # Explicit human labels are shown as option text...
        assert '>Data &amp; AI<' in content
        assert '>DevOps / SRE<' in content
        assert '>QA &amp; Testing<' in content
        # ...while the machine values remain the option values.
        assert 'value="data_ai"' in content
        assert 'value="devops_sre"' in content
        # The old humanized-key labels must be gone.
        assert 'Data Ai' not in content
        assert 'Devops Sre' not in content
        assert 'Qa Test' not in content

    def test_resolve_stores_machine_value_not_label(self, authenticated_client, sample_resume):
        self._needs_review(sample_resume)
        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            authenticated_client.post(_url(sample_resume), {'job_type': 'data_ai'})
        # Task + audit carry the machine key, never the display label.
        mock_delay.assert_called_once_with(sample_resume.id, job_type='data_ai')
        row = AuditLog.objects.get(action='resume.rescreen_requested',
                                   entity_id=str(sample_resume.uuid))
        assert 'data_ai' in row.details
        assert 'Data & AI' not in row.details


class _StartTagCollector(HTMLParser):
    """Collect every start tag as (tag, {attr: value}) for markup assertions."""

    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


@pytest.mark.django_db
class TestNeedsReviewMarkup:
    """Regression guards for the Tailwind migration of needs_review.html.

    These pin the two properties the migration must never regress: the
    Alpine wrapper/inner-flex decoupling, and the removal of the bespoke
    inline-style dark-mode hack.
    """

    def _needs_review(self, resume):
        resume.screening_status = 'needs_review'
        resume.reasoning = 'Job family uncertain from the description'
        resume.save(update_fields=['screening_status', 'reasoning'])
        return resume

    def test_no_flex_or_grid_inline_style_on_an_x_show_element(
        self, authenticated_client, sample_resume
    ):
        """Alpine decoupling: x-show toggles display, so it must never sit on an
        element whose own inline style forces display:flex/grid — that fight
        broke the layout before commit 464c306. Pins it through the rewrite."""
        self._needs_review(sample_resume)
        content = authenticated_client.get(reverse('core:needs_review')).content.decode()

        collector = _StartTagCollector()
        collector.feed(content)

        offenders = []
        for tag, attrs in collector.tags:
            if 'x-show' not in attrs:
                continue
            style = (attrs.get('style') or '').replace(' ', '').lower()
            if 'display:flex' in style or 'display:grid' in style:
                offenders.append((tag, attrs.get('x-show'), attrs.get('style')))
        assert not offenders, f"x-show sits on a flex/grid inline-styled element: {offenders}"

    def test_bespoke_inline_style_darkmode_hack_is_gone(
        self, authenticated_client, sample_resume
    ):
        """The page must render via Tailwind dark: variants, not the old
        [style*=...] attribute-matching <style> block or its .nr-root scope."""
        self._needs_review(sample_resume)
        content = authenticated_client.get(reverse('core:needs_review')).content.decode()

        assert '[style*=' not in content   # the attribute-matching selector hack
        assert 'nr-root' not in content    # the scope class it hung off of

    def test_resolve_control_and_family_options_still_render(
        self, authenticated_client, sample_resume
    ):
        """Intent of the pre-existing markup assertions, restated for this
        migration: the resolve form posts to the resolve URL and renders the
        job-family options."""
        self._needs_review(sample_resume)
        content = authenticated_client.get(reverse('core:needs_review')).content.decode()

        assert _url(sample_resume) in content       # resolve form action preserved
        assert 'Resolve &amp; re-screen' in content  # the recently-fixed submit label
        assert 'value="software_engineering"' in content  # a catalog family option
