from django.contrib import admin
from django.db.models import Count, Q
from .models import Job, Resume


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'posted_date', 'closing_date', 'resume_count', 'is_deleted')
    list_filter = ('status', 'posted_date', 'is_deleted')
    search_fields = ('title', 'description')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_per_page = 20
    
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('title', 'description', 'status')
        }),
        ('Dates', {
            'fields': ('posted_date', 'closing_date')
        }),
        ('File', {
            'fields': ('file', 'file_name', 'file_type'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at', 'is_deleted'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        """Annotate resume count to avoid N+1 queries."""
        return super().get_queryset(request).annotate(
            _resume_count=Count('resumes', filter=Q(resumes__is_deleted=False))
        )
    
    def resume_count(self, obj):
        return obj._resume_count
    resume_count.short_description = 'Resumes'
    resume_count.admin_order_field = '_resume_count'


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = ('candidate_name', 'job', 'final_score', 'tier', 'recommendation', 'created_at', 'is_deleted')
    list_filter = ('tier', 'recommendation', 'job', 'is_deleted')
    search_fields = ('candidate_name', 'job__title')
    list_select_related = ('job',)  # Prevents N+1 query for job
    date_hierarchy = 'created_at'
    ordering = ('-final_score', '-created_at')
    list_per_page = 25
    
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Candidate Info', {
            'fields': ('candidate_name', 'job')
        }),
        ('Scores', {
            'fields': ('experience_score', 'education_score', 'skills_score', 'final_score')
        }),
        ('Assessment', {
            'fields': ('tier', 'recommendation')
        }),
        ('Skills Analysis', {
            'fields': ('matched_skills', 'missing_skills'),
            'classes': ('collapse',)
        }),
        ('File', {
            'fields': ('file', 'file_name', 'file_type'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at', 'is_deleted'),
            'classes': ('collapse',)
        }),
    )