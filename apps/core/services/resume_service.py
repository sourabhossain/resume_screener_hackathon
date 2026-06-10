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

    @staticmethod
    def _fill_contact_info(resume, text: str) -> None:
        """Fill email/phone from CV text only if the recruiter left them blank."""
        update_fields = []

        if not resume.email:
            match = re.search(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', text)
            if match:
                resume.email = match.group(0)
                update_fields.append('email')

        if not resume.phone:
            # BD numbers (+8801x or 01x) or generic international format
            match = re.search(
                r'(?:\+?880[\s\-]?|0)1[3-9]\d{8}|'
                r'\+?\d[\d\s\(\)\-]{9,16}\d',
                text
            )
            if match:
                resume.phone = match.group(0).strip()
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

        result = screen_resume(resume.raw_text, resume.job.description, resume_id=resume.id, job_type="")

        if result.get('error'):
            raise AIScreeningError(result['error'], stage="screening")

        return result

    @staticmethod
    def apply_screening_result(resume, result: ScreeningResult) -> None:
        with transaction.atomic():
            from apps.core.models import Resume as ResumeModel
            resume = ResumeModel.objects.select_for_update().get(pk=resume.pk)

            resume.candidate_name = result.get('candidate_name', resume.candidate_name)
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

        # on_commit defers the task until the outermost transaction commits,
        # so this is safe even when called inside a nested atomic block.
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

            # apply_screening_result saves a separately-fetched instance, so this
            # caller's `resume` is stale; refresh before logging/returning its fields.
            resume.refresh_from_db()

            logger.info(f"Completed processing resume {resume.id}: Score={resume.final_score}")

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
            resume.screening_status = 'failed'
            resume.save(update_fields=['screening_status'])
            return {'success': False, 'error': str(e), 'error_type': 'extraction'}

        except AIScreeningError as e:
            logger.error(f"AI screening failed for resume {resume.id}: {e}")
            resume.screening_status = 'failed'
            resume.save(update_fields=['screening_status'])
            return {'success': False, 'error': str(e), 'error_type': 'screening'}

        except MissingJobDescriptionError as e:
            logger.error(f"Missing job description for resume {resume.id}: {e}")
            resume.screening_status = 'failed'
            resume.save(update_fields=['screening_status'])
            return {'success': False, 'error': str(e), 'error_type': 'job_description'}

        except Exception as e:
            logger.exception(f"Unexpected error processing resume {resume.id}: {e}")
            resume.screening_status = 'failed'
            resume.save(update_fields=['screening_status'])
            return {'success': False, 'error': str(e), 'error_type': 'unknown'}
