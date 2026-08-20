from django.contrib import admin

from .models import EmployeeForm, EmployeeFormFile


class EmployeeFormFileInline(admin.TabularInline):
    model = EmployeeFormFile
    extra = 0
    readonly_fields = ('question_key', 'file', 'original_name', 'size_bytes', 'uploaded_at')
    can_delete = False


@admin.register(EmployeeForm)
class EmployeeFormAdmin(admin.ModelAdmin):
    list_display = ('resume', 'status_label', 'invited_at', 'invite_count', 'submitted_at')
    list_filter = ('is_submitted',)
    search_fields = ('resume__candidate_name', 'resume__email')
    # Answers hold candidate PII and the OTP hash must not be editable by hand;
    # this screen is for support lookups, not data entry.
    readonly_fields = (
        'resume', 'token', 'token_expires_at', 'otp_hash', 'otp_expires_at',
        'otp_attempts', 'otp_verified_at', 'answers', 'current_step',
        'is_submitted', 'submitted_at', 'invited_at', 'invite_count',
        'invited_by', 'created_at', 'updated_at',
    )
    inlines = [EmployeeFormFileInline]

    def has_add_permission(self, request):
        # Forms are created by shortlisting a candidate, never by hand.
        return False
