from django import forms
from django.utils import timezone
from .models import Interview, InterviewEvaluation, EVALUATION_CRITERIA
from apps.core.form_utils import AriaInvalidMixin, clean_label_text, clean_person_text


INPUT = ('w-full rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-2.5 text-sm text-zinc-900 '
         'focus:border-primary-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 '
         'dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100')


def staff_evaluators():
    """Office staff who can sit on a panel: active accounts with an email address."""
    from django.contrib.auth import get_user_model
    return (get_user_model().objects.filter(is_active=True).exclude(email='')
            .order_by('first_name', 'last_name', 'username'))


def staff_label(user) -> str:
    return user.get_full_name().strip() or user.username


class InterviewCreateForm(AriaInvalidMixin, forms.ModelForm):
    evaluators = forms.ModelMultipleChoiceField(
        queryset=None, required=True, widget=forms.CheckboxSelectMultiple,
        error_messages={'required': 'Choose at least one evaluator.'})

    class Meta:
        model = Interview
        fields = ['phase', 'scheduled_date', 'scheduled_time', 'duration_minutes', 'mode',
                  'location', 'notify_candidate', 'notes']
        widgets = {
            'phase': forms.Select(attrs={'class': INPUT}),
            'scheduled_date': forms.DateInput(attrs={'type': 'date', 'class': INPUT}),
            'scheduled_time': forms.TimeInput(attrs={'type': 'time', 'class': INPUT, 'step': 300}),
            'duration_minutes': forms.Select(attrs={'class': INPUT}),
            'location': forms.TextInput(attrs={'class': INPUT}),
            'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Only your team sees these',
                                           'class': INPUT}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['evaluators'].queryset = staff_evaluators()
        self.fields['scheduled_time'].required = True
        self.fields['scheduled_date'].widget.attrs['min'] = timezone.localdate().isoformat()

    def clean_location(self):
        return (self.cleaned_data.get('location') or '').strip()

    def clean(self):
        cleaned = super().clean()
        day, at = cleaned.get('scheduled_date'), cleaned.get('scheduled_time')
        if day and day < timezone.localdate():
            self.add_error('scheduled_date', 'The date cannot be in the past.')
        elif day and at:
            from datetime import datetime
            if timezone.make_aware(datetime.combine(day, at)) < timezone.now():
                self.add_error('scheduled_time', 'That time has already passed today.')
        location, mode = cleaned.get('location', ''), cleaned.get('mode')
        if not location:
            self.add_error('location', 'Add the meeting link.' if mode == Interview.ONLINE
                           else 'Add the room or address.')
        elif mode == Interview.ONLINE:
            from django.core.validators import URLValidator
            try:
                URLValidator(schemes=['https', 'http'])(location)
            except forms.ValidationError:
                self.add_error('location', 'Paste the full meeting link, starting with https://')
        return cleaned


class StaffEvaluatorForm(forms.Form):
    """Add one more staff member to an existing panel."""
    evaluator = forms.ModelChoiceField(queryset=None, empty_label='Choose a staff member',
                                       error_messages={'required': 'Choose a staff member.'})

    def __init__(self, *args, interview=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = staff_evaluators()
        if interview is not None:
            qs = qs.exclude(pk__in=interview.evaluations.exclude(evaluator=None)
                            .values_list('evaluator_id', flat=True))
        self.fields['evaluator'].queryset = qs
        self.fields['evaluator'].label_from_instance = lambda u: f'{staff_label(u)} — {u.email}'
        self.fields['evaluator'].widget.attrs['class'] = INPUT


class InterviewerAddForm(AriaInvalidMixin, forms.ModelForm):
    """Add a new interviewer slot to an existing Interview."""
    class Meta:
        model = InterviewEvaluation
        fields = ['interviewer_name', 'interviewer_position', 'interviewer_department']
        widgets = {
            'interviewer_name': forms.TextInput(attrs={
                'placeholder': 'Full name',
                'class': 'w-full rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-2.5 text-sm text-zinc-900 focus:border-primary-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100',
            }),
            'interviewer_position': forms.TextInput(attrs={
                'placeholder': 'Position / Title',
                'class': 'w-full rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-2.5 text-sm text-zinc-900 focus:border-primary-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100',
            }),
            'interviewer_department': forms.TextInput(attrs={
                'placeholder': 'Department',
                'class': 'w-full rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-2.5 text-sm text-zinc-900 focus:border-primary-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100',
            }),
        }
        labels = {
            'interviewer_name': 'Name',
            'interviewer_position': 'Position',
            'interviewer_department': 'Department',
        }

    def clean_interviewer_name(self):
        return clean_person_text(self.cleaned_data.get('interviewer_name'), required=True)

    def clean_interviewer_position(self):
        return clean_label_text(self.cleaned_data.get('interviewer_position'))

    def clean_interviewer_department(self):
        return clean_label_text(self.cleaned_data.get('interviewer_department'))


SCORE_CHOICES = [(i, str(i)) for i in range(1, 6)]


class EvaluationSubmitForm(forms.Form):
    """Public form filled by the interviewer via unique token link."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key, label in EVALUATION_CRITERIA:
            self.fields[f'score_{key}'] = forms.ChoiceField(
                label=label,
                choices=SCORE_CHOICES,
                widget=forms.RadioSelect(attrs={'class': 'score-radio'}),
            )

        self.fields['recommendation'] = forms.ChoiceField(
            label='Recommendation',
            choices=[('', '- Select -')] + list(InterviewEvaluation.RECOMMENDATION_CHOICES),
            required=False,
            widget=forms.Select(attrs={
                'class': 'w-full rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-2.5 text-sm text-zinc-900 focus:border-primary-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-200',
            }),
        )
        for fname, flabel in [
            ('another_phase_required', 'Another interview phase required'),
            ('hard_negotiation', 'Hard negotiation expected'),
            ('suitable_other_dept', 'Suitable for another department'),
            ('suitable_higher_position', 'Suitable for a higher position'),
            ('suitable_junior_position', 'Suitable for a junior position'),
        ]:
            self.fields[fname] = forms.BooleanField(label=flabel, required=False)

        self.fields['additional_notes'] = forms.CharField(
            label='Additional Notes',
            required=False,
            widget=forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Any other observations…',
                'class': 'w-full rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-2.5 text-sm focus:border-primary-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-200',
            }),
        )
