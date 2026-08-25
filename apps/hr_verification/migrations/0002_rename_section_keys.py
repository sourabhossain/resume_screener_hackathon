"""Carry existing records across the section rename.

The six sections were keyed `section_a`..`section_f` and are now named
(`hr_review`..`clearance`); one answer key was renamed with them. Those old
values are stored in `completed_steps` and `answers`, and `completed_count`
intersects with the current schema -- so without this a record saved before the
rename reads as "Not started", loses sign-off eligibility, and shows its recorded
completion date as blank.

Reversible: the same mapping applied the other way.
"""
from django.db import migrations

SECTION_KEYS = {
    'section_a': 'hr_review',
    'section_b': 'identity',
    'section_c': 'education',
    'section_d': 'employment',
    'section_e': 'references',
    'section_f': 'clearance',
}

ANSWER_KEYS = {
    'section_e_completion_date': 'verification_completion_date',
}


def _remap(apps, sections, answers):
    HRVerification = apps.get_model('hr_verification', 'HRVerification')
    for record in HRVerification.objects.all().iterator():
        changed = False

        done = list(record.completed_steps or [])
        renamed = [sections.get(key, key) for key in done]
        # De-duplicated in case both names somehow ended up stored.
        deduped = list(dict.fromkeys(renamed))
        if deduped != done:
            record.completed_steps = deduped
            changed = True

        stored = dict(record.answers or {})
        for old, new in answers.items():
            if old in stored:
                stored.setdefault(new, stored.pop(old))
                changed = True
        if changed:
            record.answers = stored
            record.save(update_fields=['completed_steps', 'answers'])


def forwards(apps, schema_editor):
    _remap(apps, SECTION_KEYS, ANSWER_KEYS)


def backwards(apps, schema_editor):
    _remap(apps,
           {new: old for old, new in SECTION_KEYS.items()},
           {new: old for old, new in ANSWER_KEYS.items()})


class Migration(migrations.Migration):

    dependencies = [
        ('hr_verification', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
