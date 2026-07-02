import logging
import re
from typing import Dict, Any

from django.db import transaction

from apps.core.exceptions import (
    DocumentExtractionError,
    AIScreeningError,
    MissingJobDescriptionError
)
from apps.core.types import ScreeningResult

logger = logging.getLogger(__name__)

class ResumeService:

    @staticmethod
    def extract_text(resume) -> str:
        from apps.core.services.document_extractor import DocumentExtractor

        if resume.raw_text:
            return resume.raw_text

        if not resume.file:
            raise DocumentExtractionError("No file attached to resume")

        try:
            text = DocumentExtractor.extract(resume.file.path)
            if not text or not text.strip():
                raise DocumentExtractionError(
                    "No text could be extracted from the file. "
                    "It may be a scanned image or an empty document. "
                    "Please upload a text-based PDF or DOCX.",
                    file_path=resume.file.path
                )
            resume.raw_text = text
            resume.save(update_fields=['raw_text'])
            return text
        except DocumentExtractionError:
            raise
        except Exception as e:
            raise DocumentExtractionError(str(e), file_path=resume.file.path)

    _PHONE_RE = re.compile(
        r'(?:\+?880[\s \-]?|0)1[3-9][\d]{8}'
        r'|\+\d[\d\s\(\)\-]{9,16}\d'
    )
    _EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

    @classmethod
    def _extract_email(cls, text: str):
        """Return (email_str, position) or ('', -1). Handles PDF spacing artifacts."""
        m = cls._EMAIL_RE.search(text)
        if m:
            return m.group(0), m.start()
        for at_m in re.finditer(r'@', text):
            pos = at_m.start()
            window = text[max(0, pos - 60): pos + 60]
            cleaned = re.sub(r'(?<=[A-Za-z0-9._%+\-]) (?=[A-Za-z0-9._%+\-])', '', window)
            m2 = cls._EMAIL_RE.search(cleaned)
            if m2:
                return m2.group(0), pos
        return '', -1

    @classmethod
    def _extract_phone(cls, text: str, email_pos: int = -1) -> str:
        """Return the candidate's own phone.
        When multiple phones exist (e.g. a reference contact), prefers the phone
        nearest to the candidate's email address in the extracted text.
        """
        matches = [(m.start(), re.sub(r'[\s ]', '', m.group(0))) for m in cls._PHONE_RE.finditer(text)]
        if not matches:
            return ''
        if len(matches) == 1:
            return matches[0][1]
        if email_pos >= 0:
            return min(matches, key=lambda x: abs(x[0] - email_pos))[1]
        return matches[-1][1]

    @classmethod
    def _fill_contact_info(cls, resume, text: str) -> None:
        """Fill email/phone from CV text only if the recruiter left them blank."""
        update_fields = []
        email_pos = -1

        if not resume.email:
            email, email_pos = cls._extract_email(text)
            if email:
                resume.email = email
                update_fields.append('email')
        else:
            m = re.search(re.escape(resume.email), text)
            email_pos = m.start() if m else -1

        if not resume.phone:
            phone = cls._extract_phone(text, email_pos)
            if phone:
                resume.phone = phone
                update_fields.append('phone')

        if update_fields:
            resume.save(update_fields=update_fields)

    @staticmethod
    def run_screening(resume) -> ScreeningResult:
        from apps.core.services.ai_screener import screen_resume

        if not resume.job.description:
            raise MissingJobDescriptionError(resume.job.id)

        if not resume.raw_text:
            raise AIScreeningError("No resume text available", stage="extraction")

        result = screen_resume(
            resume.raw_text, resume.job.description,
            resume_id=resume.id, job_type="",
            required_experience=resume.job.required_experience,
            required_skills=resume.job.required_skills,
        )

        if result.get('error'):
            raise AIScreeningError(result['error'], stage="screening")

        return result

    @staticmethod
    def apply_screening_result(resume, result: ScreeningResult) -> None:
        if result.get('needs_review'):
            from apps.core.models import Resume as ResumeModel
            ResumeModel.objects.filter(pk=resume.pk).update(
                screening_status='needs_review',
                reasoning=result.get('reasoning', '') or '',
                final_score=None,
                tier='',
                recommendation='',
                skills_score=None,
                experience_score=None,
                education_score=None,
                certification_score=None,
                achievement_score=None,
            )
            return

        with transaction.atomic():
            from apps.core.models import Resume as ResumeModel
            resume = ResumeModel.objects.select_for_update().get(pk=resume.pk)

            resume.candidate_name = result.get('candidate_name', resume.candidate_name)
            if not resume.email and result.get('candidate_email'):
                resume.email = result['candidate_email']
            if not resume.phone and result.get('candidate_phone'):
                resume.phone = result['candidate_phone']
            resume.skills = result.get('skills', [])
            resume.education = result.get('education', [])
            resume.certifications = result.get('certifications', [])
            resume.achievements = result.get('achievements', [])
            resume.experience_years = round(result.get('experience_years', 0), 1)
            resume.matched_skills = result.get('matched_skills', [])
            resume.missing_skills = result.get('missing_skills', [])
            resume.skills_score = round(result.get('skill_score', 0))
            resume.experience_score = round(result.get('experience_score', 0))
            resume.education_score = round(result.get('education_score', 0))
            resume.certification_score = round(result.get('certification_score', 0))
            resume.achievement_score = round(float(result.get('achievement_score') or 0))
            resume.final_score = round(result.get('final_score', 0))
            resume.reasoning = result.get('reasoning', '')
            resume.screening_status = 'completed'
            resume.save()

        from apps.core.tasks import verify_resume_links_task
        transaction.on_commit(lambda: verify_resume_links_task.delay(resume.id))

    @classmethod
    def process_resume(cls, resume) -> Dict[str, Any]:
        try:
            resume.screening_status = 'processing'
            resume.save(update_fields=['screening_status'])

            raw_text = cls.extract_text(resume)
            cls._fill_contact_info(resume, raw_text)
            result = cls.run_screening(resume)
            cls.apply_screening_result(resume, result)

            resume.refresh_from_db()

            from apps.core.services.audit import audit_log

            if resume.screening_status == 'needs_review':
                logger.info(f"Resume {resume.id} flagged for manual review (job family uncertain)")
                audit_log(None, 'resume.screening_needs_review', resume)
                return {
                    'success': True,
                    'resume_id': resume.id,
                    'needs_review': True,
                    'screening_status': 'needs_review',
                }

            logger.info(f"Completed processing resume {resume.id}: Score={resume.final_score}")

            audit_log(None, 'resume.screening_completed', resume,
                      details=f'final_score={resume.final_score} tier={resume.tier}')
            return {
                'success': True,
                'resume_id': resume.id,
                'candidate_name': resume.candidate_name,
                'final_score': resume.final_score,
                'tier': resume.tier,
                'recommendation': resume.recommendation
            }

        except DocumentExtractionError as e:
            logger.error(f"Document extraction failed for resume {resume.id}: {e}")
            cls._mark_failed(resume, f"Couldn't read the résumé file — {e}")
            return {'success': False, 'error': str(e), 'error_type': 'extraction'}

        except AIScreeningError as e:
            logger.error(f"AI screening failed for resume {resume.id}: {e}")
            cls._mark_failed(resume, f"AI screening error — {e}")
            return {'success': False, 'error': str(e), 'error_type': 'screening'}

        except MissingJobDescriptionError as e:
            logger.error(f"Missing job description for resume {resume.id}: {e}")
            cls._mark_failed(
                resume,
                "This job has no description, so the résumé couldn't be screened. "
                "Add a job description, then re-run screening.",
            )
            return {'success': False, 'error': str(e), 'error_type': 'job_description'}

        except Exception as e:
            logger.exception(f"Unexpected error processing resume {resume.id}: {e}")
            cls._mark_failed(resume, f"Unexpected error during screening — {e}")
            return {'success': False, 'error': str(e), 'error_type': 'unknown'}

    @staticmethod
    def _mark_failed(resume, reason: str) -> None:
        """Mark a résumé failed AND persist WHY (shown on the Screening Failed page)."""
        resume.screening_status = 'failed'
        resume.reasoning = reason
        resume.save(update_fields=['screening_status', 'reasoning'])

        from apps.core.services.audit import audit_log
        audit_log(None, 'resume.screening_failed', resume)
