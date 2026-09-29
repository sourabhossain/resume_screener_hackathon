"""Read-only view of a verification: only questions visible for the saved answers."""
from apps.core.documents import display_date
from apps.core.form_logic import is_visible

from . import schema

# Q40 / Q42: start + "Current" tick + end, shown as one period row.
_PERIOD_PARTS = ('start_date', 'current', 'end_date')


def display_value(answers, question):
    if question['type'] in schema.FILE_TYPES:
        return ''
    raw = (answers or {}).get(question['key'])
    if raw in (None, '', []):
        return ''
    if question['type'] == schema.BOOLEAN:
        return 'Yes' if raw in ('yes', True) else ''
    if question['type'] == schema.CHECKBOX:
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        return ', '.join(str(schema.choice_label(question['key'], v)) for v in values)
    if question['type'] in schema.CHOICE_TYPES:
        return schema.choice_label(question['key'], raw)
    if question['type'] == schema.DATE:
        return display_date(raw)
    return raw


def _period(answers, key):
    """('Candidate-claimed Employment Period', '01 Jan 2020 – Current') for a start key."""
    base = key[:-len('_start_date')]
    start = display_date(answers.get(key)) if answers.get(key) else ''
    if answers.get(f'{base}_current') in ('yes', True):
        end = 'Current'
    else:
        end = display_date(answers.get(f'{base}_end_date')) if answers.get(f'{base}_end_date') else ''
    if not (start or end):
        return ''
    return f"{start or '—'} – {end or '—'}"


def _is_period_part(key):
    return key.endswith(('_claimed_current', '_claimed_end_date',
                         '_confirmed_current', '_confirmed_end_date'))


def _rows(answers, block_questions, files_by_key):
    rows = []
    for question in block_questions:
        key = question['key']
        if not is_visible(question, answers) or _is_period_part(key):
            continue
        label = schema.wizard_label(question)
        if key.endswith(('_claimed_start_date', '_confirmed_start_date')):
            value = _period(answers, key)
            label = label.rsplit(' — ', 1)[0]
        else:
            value = display_value(answers, question)
        files = files_by_key.get(key, [])
        if value == '' and not files:
            continue
        rows.append({'key': key, 'label': label, 'value': value, 'files': files})
    return rows


def _grid_block(answers, grid):
    columns = [label for _, label, *_ in grid['columns']]
    table = []
    for prefix, row_label, _ in grid['rows']:
        cells, any_answer, shown = [], False, False
        for suffix, *_ in grid['columns']:
            question = schema.QUESTIONS_BY_KEY[f'{prefix}_{suffix}']
            shown = shown or is_visible(question, answers)
            value = display_value(answers, question) if is_visible(question, answers) else ''
            any_answer = any_answer or value != ''
            cells.append(value)
        if shown and any_answer:
            table.append({'label': row_label, 'cells': cells})
    if not table:
        return None
    return {'title': grid['title'], 'kind': 'grid', 'columns': columns, 'table': table}


def build_sections(answers, files_by_key, is_complete):
    answers = schema.legacy_view(answers)
    out = []
    for step_key in schema.STEP_KEYS:
        step = schema.get_step(step_key)
        blocks, seen_grids = [], set()
        for block in schema.question_groups(step_key):
            grid = block['grid']
            if grid is not None:
                if grid['title'] in seen_grids:
                    continue
                seen_grids.add(grid['title'])
                built = _grid_block(answers, grid)
                if built:
                    blocks.append(built)
                continue
            rows = _rows(answers, block['questions'], files_by_key)
            if rows:
                blocks.append({'title': block['title'], 'kind': 'rows', 'rows': rows})
        out.append({
            'key': step_key,
            'section': step['section'],
            'title': step['title'],
            'complete': is_complete(step_key),
            'blocks': blocks,
        })
    return out
