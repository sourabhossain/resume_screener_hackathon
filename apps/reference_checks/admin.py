from django.contrib import admin

from .models import ReferenceCheck


@admin.register(ReferenceCheck)
class ReferenceCheckAdmin(admin.ModelAdmin):
    list_display = ('resume', 'kind', 'source_key', 'recipient_name',
                    'status_label', 'flagged', 'updated_at')
    list_filter = ('kind', 'is_submitted')
    search_fields = ('resume__candidate_name', 'recipient_name', 'recipient_email')
    # answers hold a third party's disclosures about someone's employment; the
    # admin is not where those get hand-edited.
    readonly_fields = ('resume', 'kind', 'source_key', 'token', 'otp_hash',
                       'answers', 'submitted_at', 'invited_at', 'invited_by',
                       'created_at', 'updated_at')
