import pytest
from django.db import IntegrityError

from apps.core.models import AuditLog
from apps.core.services import audit_log


@pytest.mark.django_db
class TestAuditLogAppendOnly:
    def _row(self):
        return AuditLog.objects.create(action='job.created', entity_type='job', entity_id='x')

    def test_save_on_existing_pk_raises_and_leaves_row_unchanged(self):
        row = self._row()
        row.details = 'mutated'
        with pytest.raises(IntegrityError):
            row.save()
        row.refresh_from_db()
        assert row.details == ''

    def test_queryset_update_raises_and_leaves_row_unchanged(self):
        self._row()
        with pytest.raises(IntegrityError):
            AuditLog.objects.all().update(details='mutated')
        assert AuditLog.objects.get().details == ''

    def test_queryset_bulk_update_raises_and_leaves_row_unchanged(self):
        row = self._row()
        row.details = 'mutated'
        with pytest.raises(IntegrityError):
            AuditLog.objects.bulk_update([row], ['details'])
        row.refresh_from_db()
        assert row.details == ''

    def test_queryset_delete_raises_and_row_survives(self):
        self._row()
        with pytest.raises(IntegrityError):
            AuditLog.objects.all().delete()
        assert AuditLog.objects.count() == 1

    def test_model_delete_raises(self):
        row = self._row()
        with pytest.raises(IntegrityError):
            row.delete()
        assert AuditLog.objects.count() == 1


@pytest.mark.django_db
class TestAuditLogService:
    def test_resolves_resume_to_uuid(self, sample_resume):
        audit_log(None, 'resume.uploaded', sample_resume)
        row = AuditLog.objects.get()
        assert row.entity_type == 'resume'
        assert row.entity_id == str(sample_resume.uuid)

    def test_resolves_job_to_slug(self, sample_job):
        audit_log(None, 'job.created', sample_job)
        row = AuditLog.objects.get()
        assert row.entity_type == 'job'
        assert row.entity_id == sample_job.slug

    def test_actor_none_for_system_action(self, sample_job):
        audit_log(None, 'job.auto_closed', sample_job)
        assert AuditLog.objects.get().actor is None

    def test_actor_recorded_when_supplied(self, sample_job, user):
        audit_log(user, 'job.created', sample_job)
        assert AuditLog.objects.get().actor == user

    def test_request_id_populated_from_request(self, sample_job):
        class _Req:
            request_id = 'abcd1234'
        audit_log(None, 'job.created', sample_job, request=_Req())
        assert AuditLog.objects.get().request_id == 'abcd1234'

    def test_never_raises_and_writes_nothing_when_save_fails(self, sample_job, monkeypatch):
        def _boom(self, *a, **k):
            raise RuntimeError('db unavailable')
        monkeypatch.setattr(AuditLog, 'save', _boom)
        audit_log(None, 'job.created', sample_job)  # must not raise
        monkeypatch.undo()
        assert AuditLog.objects.count() == 0
