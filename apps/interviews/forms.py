from django import forms
from .models import Interview, InterviewEvaluation, EVALUATION_CRITERIA
from apps.core.form_utils import AriaInvalidMixin, clean_label_text, clean_person_text


class InterviewCreateForm(AriaInvalidMixin, forms.ModelForm):
    class Meta:
        model = Interview
        fields = ['phase', 'scheduled_date', 'notes']
        widgets = {
            'phase': forms.Select(attrs={
                'class': 'w-full rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-2.5 text-sm text-zinc-900 focus:border-primary-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100',
            }),
            'scheduled_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-2.5 text-sm text-zinc-900 focus:border-primary-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Optional notes…',
                'class': 'w-full rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-2.5 text-sm text-zinc-900 focus:border-primary-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100',
            }),
        }


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
            choices=[('', '— Select —')] + list(InterviewEvaluation.RECOMMENDATION_CHOICES),
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
