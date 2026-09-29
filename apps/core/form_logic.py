"""Show/require rules for schema-driven forms, evaluated the same way in Python and JS.

A rule is plain data so it can be shipped to the page as JSON:
    {'q': key, 'in': [values]}   answer (or any checked value) is one of values
    {'q': key, 'filled': True}   answer is not blank
    {'all': [rules]}, {'any': [rules]}, {'not': rule}

A question may carry `show_if` (hidden and cleared unless true) and `required_if`
(required only while true). `required` on a question means required while shown.
"""

EMPTY = (None, '', [], ())


def is_blank(value) -> bool:
    if isinstance(value, str):
        return not value.strip()
    return value in EMPTY


def when(key, *values):
    return {'q': key, 'in': list(values)}


def filled(key):
    return {'q': key, 'filled': True}


def all_of(*rules):
    return {'all': [r for r in rules if r]}


def any_of(*rules):
    return {'any': [r for r in rules if r]}


def negate(rule):
    return {'not': rule}


def evaluate(rule, answers) -> bool:
    if not rule:
        return True
    if 'all' in rule:
        return all(evaluate(r, answers) for r in rule['all'])
    if 'any' in rule:
        return any(evaluate(r, answers) for r in rule['any'])
    if 'not' in rule:
        return not evaluate(rule['not'], answers)
    value = answers.get(rule['q'])
    if rule.get('filled'):
        return not is_blank(value)
    options = set(rule.get('in') or ())
    if isinstance(value, (list, tuple)):
        return bool(options.intersection(value))
    return value in options


def rule_keys(rule) -> set:
    if not rule:
        return set()
    if 'all' in rule or 'any' in rule:
        return set().union(*(rule_keys(r) for r in rule.get('all') or rule.get('any')))
    if 'not' in rule:
        return rule_keys(rule['not'])
    return {rule['q']}


def is_visible(question, answers) -> bool:
    return evaluate(question.get('show_if'), answers)


def is_required(question, answers) -> bool:
    if not is_visible(question, answers):
        return False
    if question.get('required'):
        return True
    return bool(question.get('required_if')) and evaluate(question['required_if'], answers)


def is_conditional(question) -> bool:
    return bool(question.get('show_if') or question.get('required_if'))


def page_rules(questions):
    """{key: {'show_if', 'required_if', 'required'}} for the questions on one page."""
    return {
        q['key']: {
            'show_if': q.get('show_if'),
            'required_if': q.get('required_if'),
            'required': bool(q.get('required')),
        }
        for q in questions if is_conditional(q)
    }


def context_answers(questions, answers):
    """Stored answers that rules on this page read but that live on another page."""
    on_page = {q['key'] for q in questions}
    needed = set()
    for q in questions:
        needed |= rule_keys(q.get('show_if')) | rule_keys(q.get('required_if'))
    return {k: answers.get(k) for k in needed - on_page}


def missing_required(questions, answers, uploaded=frozenset()):
    """Keys of questions required by these answers but left blank."""
    out = []
    for q in questions:
        if not is_required(q, answers):
            continue
        if q['key'] in uploaded:
            continue
        if is_blank(answers.get(q['key'])):
            out.append(q['key'])
    return out


def blank_for(question, file_types):
    if question['type'] in file_types:
        return None
    if question['type'] == 'checkbox':
        return []
    return ''


class ConditionalFormMixin:
    """Hide-and-clear plus conditional requirement for a schema StepForm.

    The subclass sets `self.questions` and builds fields with `required=False`
    for any conditional question, then calls `apply_logic(cleaned)` from clean().
    """

    logic_file_types = frozenset({'file', 'files', 'signature'})
    logic_context = None

    def logic_answers(self, cleaned):
        answers = dict(self.logic_context or {})
        answers.update(self.initial or {})
        for q in self.questions:
            if q['key'] in cleaned:
                answers[q['key']] = cleaned[q['key']]
            elif q['key'] in getattr(self, 'already_uploaded', ()):
                answers.setdefault(q['key'], True)
        return answers

    def apply_logic(self, cleaned):
        self.hidden_keys = []
        answers = self.logic_answers(cleaned)
        for q in self.questions:
            key = q['key']
            if not is_visible(q, answers):
                self.hidden_keys.append(key)
                self.errors.pop(key, None)
                cleaned[key] = blank_for(q, self.logic_file_types)
                answers[key] = cleaned[key]
        for q in self.questions:
            key = q['key']
            if key in self.hidden_keys or self.errors.get(key):
                continue
            if not is_conditional(q):
                continue
            if not is_required(q, answers):
                continue
            if key in getattr(self, 'already_uploaded', ()):
                continue
            if is_blank(cleaned.get(key)):
                self.add_error(key, 'This field is required.')
        return cleaned

    def hidden_file_keys(self):
        return [
            q['key'] for q in self.questions
            if q['key'] in getattr(self, 'hidden_keys', ())
            and q['type'] in self.logic_file_types
        ]
