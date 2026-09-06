"""Structural rules every schema-driven form must obey.

The four form apps -- employee_form, hr_verification, candidate_mapping and
reference_checks -- are all data: a list of steps, each holding a list of
questions. That makes them easy to extend and easy to break quietly, because a
mistyped key or a choice list built by concatenation raises nothing at import
time. These tests read whatever the schemas currently say and assert the rules
that hold for all of them, so a new section is covered the day it is added
rather than the day someone notices the form misbehaving.
"""
import pytest

from apps.candidate_mapping import schema as cm
from apps.employee_form import schema as ef
from apps.hr_verification import schema as hv
from apps.reference_checks import schema as rc

CHOICE_TYPES = ('select', 'radio', 'checkbox')


def _forms():
    """Every form in the project, as (label, steps, questions_by_key)."""
    for label, module in (('employee_form', ef),
                          ('hr_verification', hv),
                          ('candidate_mapping', cm)):
        steps = module.STEPS
        yield label, steps, {q['key']: q for s in steps for q in s['questions']}

    for kind in (rc.EMPLOYER, rc.PROFESSIONAL, rc.ACADEMIC):
        yield f'reference_checks/{kind}', rc.steps(kind), rc.questions_by_key(kind)


FORMS = list(_forms())
FORM_IDS = [label for label, _, _ in FORMS]
QUESTIONS = [(label, q) for label, steps, _ in FORMS
             for s in steps for q in s['questions']]
QUESTION_IDS = [f'{label}:{q["key"]}' for label, q in QUESTIONS]


@pytest.mark.parametrize('label,question', QUESTIONS, ids=QUESTION_IDS)
def test_no_question_offers_the_same_choice_twice(label, question):
    """A duplicated value renders the same option twice and makes the second
    unselectable -- how "Other" came to appear twice on the HR form."""
    values = [v for v, _ in (question.get('choices') or [])]
    duplicates = sorted({v for v in values if values.count(v) > 1})
    assert not duplicates, f'{label}:{question["key"]} repeats {duplicates}'


@pytest.mark.parametrize('label,question', QUESTIONS, ids=QUESTION_IDS)
def test_choice_questions_have_usable_choices(label, question):
    where = f'{label}:{question["key"]}'
    if question['type'] in CHOICE_TYPES:
        assert question.get('choices'), f'{where} is a {question["type"]} with no choices'
    for value, text in (question.get('choices') or []):
        assert value != '', f'{where} has an empty choice value'
        assert str(text).strip(), f'{where} has a choice with no label'


@pytest.mark.parametrize('label,steps,by_key', FORMS, ids=FORM_IDS)
def test_question_keys_are_unique_within_a_form(label, steps, by_key):
    """Answers are one JSON blob per form, so a reused key means one section
    silently overwrites the other's answer."""
    seen = {}
    for step in steps:
        for question in step['questions']:
            assert question['key'] not in seen, (
                f'{label}: {question["key"]!r} is in both {seen.get(question["key"])!r} '
                f'and {step["key"]!r}'
            )
            seen[question['key']] = step['key']


@pytest.mark.parametrize('label,steps,by_key', FORMS, ids=FORM_IDS)
def test_step_keys_are_unique(label, steps, by_key):
    keys = [s['key'] for s in steps]
    assert len(keys) == len(set(keys)), f'{label}: duplicate step keys in {keys}'


@pytest.mark.parametrize('label,steps,by_key', FORMS, ids=FORM_IDS)
def test_every_next_points_at_a_real_step(label, steps, by_key):
    """employee_form routes by department with a callable; the rest name the
    next step directly, and a typo there strands the respondent."""
    keys = {s['key'] for s in steps}
    for step in steps:
        nxt = step.get('next')
        if nxt is None or callable(nxt):
            continue
        assert nxt in keys, f'{label}: {step["key"]!r} points at missing {nxt!r}'


@pytest.mark.parametrize('label,steps,by_key', FORMS, ids=FORM_IDS)
def test_every_step_is_reachable(label, steps, by_key):
    """Follow every branch a router can take and confirm nothing is orphaned."""
    keys = [s['key'] for s in steps]
    by_step = {s['key']: s for s in steps}
    reached, queue = set(), [keys[0]]
    while queue:
        cur = queue.pop()
        if cur in reached:
            continue
        reached.add(cur)
        nxt = by_step[cur].get('next')
        if callable(nxt):
            # A router picks among the steps that follow it; treat them all as
            # reachable rather than guessing which inputs select which.
            queue.extend(keys[keys.index(cur) + 1:])
        elif nxt:
            queue.append(nxt)
    assert reached == set(keys), f'{label}: unreachable steps {sorted(set(keys) - reached)}'


def _rules(label, steps):
    if label.startswith('reference_checks/'):
        kind = label.split('/', 1)[1]
        return [r for k in rc.step_keys(kind) for r in rc.conditional_rules(kind, k)]
    module = {'employee_form': ef, 'hr_verification': hv,
              'candidate_mapping': cm}[label]
    rules = getattr(module, 'CONDITIONAL_RULES', [])
    if isinstance(rules, dict):
        return [r for group in rules.values() for r in group]
    return list(rules)


@pytest.mark.parametrize('label,steps,by_key', FORMS, ids=FORM_IDS)
def test_conditional_rules_reference_real_questions_and_values(label, steps, by_key):
    """A rule that waits on a value the question never offers is a field that
    can never become required -- and one naming a missing key is dead."""
    for rule in _rules(label, steps):
        trigger = rule['trigger']
        assert trigger in by_key, f'{label}: rule trigger {trigger!r} is not a question'

        offered = {v for v, _ in (by_key[trigger].get('choices') or [])}
        if offered:
            unknown = [w for w in rule.get('when', []) if w not in offered]
            assert not unknown, (
                f'{label}: rule on {trigger!r} waits for {unknown}, '
                f'but it offers {sorted(offered)}'
            )

        for key in rule.get('keys', []):
            assert key in by_key, f'{label}: rule target {key!r} is not a question'
