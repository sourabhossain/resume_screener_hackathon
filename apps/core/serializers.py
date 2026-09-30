"""
Django REST Framework Serializers for Job and Resume.
"""
from django import forms as dj_forms
from rest_framework import serializers

from .forms import FileValidationMixin
from .models import Job, Resume



class ResumeSerializer(serializers.ModelSerializer):
    """Serializer for Resume with computed display fields."""
    tier_display = serializers.CharField(source='get_tier_display', read_only=True)
    recommendation_display = serializers.CharField(source='get_recommendation_display', read_only=True)
    screening_status_display = serializers.CharField(source='get_screening_status_display', read_only=True)
    verification_status_display = serializers.CharField(source='get_verification_status_display', read_only=True)

    # Read-only here: scores are the model's, or a person's through the edit
    # page, which records who changed them. The API has no such audit trail.
    experience_score = serializers.FloatField(read_only=True)
    education_score = serializers.FloatField(read_only=True)
    skills_score = serializers.FloatField(read_only=True)
    certification_score = serializers.FloatField(read_only=True)
    final_score = serializers.FloatField(read_only=True)

    class Meta:
        model = Resume
        fields = [
            'id', 'job', 'candidate_name', 'email', 'phone',
            'file', 'file_name', 'file_type',
            'tier', 'tier_display', 'recommendation', 'recommendation_display',
            'screening_status', 'screening_status_display',
            'experience_score', 'education_score', 'skills_score',
            'certification_score', 'achievement_score', 'final_score',
            'matched_skills', 'missing_skills', 'skills', 'education', 'certifications',
            'achievements',
            'reasoning',
            'extracted_links', 'verification_results', 'verification_status',
            'verification_status_display', 'verification_score', 'verified_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'file_name', 'file_type', 'created_at', 'updated_at',
            'tier', 'tier_display', 'recommendation', 'recommendation_display',
            'screening_status', 'screening_status_display',
            'achievement_score', 'skills', 'education', 'certifications', 'achievements',
            'matched_skills', 'missing_skills', 'reasoning',
            'extracted_links', 'verification_results', 'verification_status',
            'verification_status_display', 'verification_score', 'verified_at',
        ]


    def validate_file(self, upload):
        """The same type, size and content checks as the upload pages."""
        try:
            return FileValidationMixin().validate_resume_file(upload)
        except dj_forms.ValidationError as exc:
            raise serializers.ValidationError(exc.messages)

    def validate_candidate_name(self, value):
        from .form_utils import clean_person_text
        try:
            return clean_person_text(value, required=True)
        except dj_forms.ValidationError as exc:
            raise serializers.ValidationError(exc.messages)


class JobListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for job listings."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    resume_count = serializers.IntegerField(read_only=True)  # Expects annotation from viewset
    
    class Meta:
        model = Job
        fields = [
            'id', 'title', 'status', 'status_display',
            'posted_date', 'closing_date', 'resume_count', 'created_at'
        ]


class JobDetailSerializer(serializers.ModelSerializer):
    """Full serializer for job details with resumes."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    resumes = ResumeSerializer(many=True, read_only=True, source='_active_resumes')
    resume_count = serializers.IntegerField(read_only=True)  # Uses annotation from viewset
    
    class Meta:
        model = Job
        fields = [
            'id', 'title', 'description', 'status', 'status_display',
            'posted_date', 'closing_date',
            'file', 'file_name', 'file_type',
            'required_skills', 'required_experience', 'required_education',
            'resume_count', 'resumes',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'file_name', 'file_type', 'created_at', 'updated_at']

