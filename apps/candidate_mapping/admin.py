from django.contrib import admin

from .models import CandidateMapping, CandidateMappingFile


class CandidateMappingFileInline(admin.TabularInline):
    model = CandidateMappingFile
    extra = 0
    readonly_fields = ('question_key', 'original_name', 'size_bytes',
                       'uploaded_at', 'uploaded_by')


@admin.register(CandidateMapping)
class CandidateMappingAdmin(admin.ModelAdmin):
    list_display = ('resume', 'status_label', 'completed_count', 'outcome_label',
                    'updated_at')
    list_filter = ('is_submitted',)
    search_fields = ('resume__candidate_name', 'resume__email')
    # The answers blob holds adverse findings; the admin is not where those get
    # hand-edited.
    readonly_fields = ('resume', 'answers', 'completed_steps', 'submitted_at',
                       'submitted_by', 'started_by', 'last_saved_by',
                       'created_at', 'updated_at')
    inlines = [CandidateMappingFileInline]
