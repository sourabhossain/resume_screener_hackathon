"""The declaration signature: drawn on the canvas, or uploaded as a file.

Exercised at the form rather than through the wizard, because reaching
d7_declaration means walking every preceding step and none of that is what
these assertions are about.
"""
import base64

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.employee_form import schema
from apps.employee_form.forms import StepForm
from apps.employee_form.tests.helpers import (
    PNG_1PX_BASE64,
    SIGNATURE_DATA_URL,
    signature_upload,
)

STEP = 'd7_declaration'

BASE = {
    'total_experience_years': '5',
    'current_responsibilities': 'Everything',
    'measurable_achievements': 'Many',
    'availability_status': 'immediately_available',
    'declaration_agreement': 'agree',
}


def _form(data=None, files=None, **kwargs):
    return StepForm({**BASE, **(data or {})}, files or {}, step_key=STEP, **kwargs)


def test_the_typed_signature_and_declaration_date_are_gone():
    keys = {q['key'] for q in schema.get_step(STEP)['questions']}
    assert 'typed_signature' not in keys
    assert 'declaration_date' not in keys
    assert 'signature' in keys


def test_a_drawn_signature_is_accepted():
    form = _form({'signature_drawn': SIGNATURE_DATA_URL})

    assert form.is_valid(), form.errors
    upload = form.cleaned_data['signature']
    assert upload.read().startswith(b'\x89PNG\r\n\x1a\n')


def test_an_uploaded_signature_is_accepted():
    form = _form(files={'signature': signature_upload()})

    assert form.is_valid(), form.errors
    assert form.cleaned_data['signature']


def test_a_missing_signature_is_rejected():
    form = _form()

    assert not form.is_valid()
    assert 'signature' in form.errors


def test_an_empty_drawing_is_treated_as_no_signature():
    """The canvas posts an empty string when nothing was drawn on it."""
    form = _form({'signature_drawn': ''})

    assert not form.is_valid()
    assert 'signature' in form.errors


def test_an_upload_wins_over_a_drawing():
    """Picking a file after drawing is the candidate changing their mind."""
    chosen = base64.b64decode(PNG_1PX_BASE64)
    form = _form(
        {'signature_drawn': SIGNATURE_DATA_URL},
        {'signature': SimpleUploadedFile('mine.png', chosen, content_type='image/png')},
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data['signature'].name == 'mine.png'


@pytest.mark.parametrize('drawn', [
    'not-a-data-url',
    'data:text/html;base64,' + PNG_1PX_BASE64,        # wrong media type
    'data:image/png;base64,@@@not-base64@@@',
    'data:image/png;base64,' + base64.b64encode(b'%PDF-1.4 not a png').decode(),
])
def test_a_tampered_drawing_is_rejected(drawn):
    """The data: URL is candidate-controlled text, so it is not taken on trust."""
    form = _form({'signature_drawn': drawn})

    assert not form.is_valid()
    assert 'signature' in form.errors


def test_an_oversized_drawing_is_rejected_before_decoding():
    form = _form({'signature_drawn': 'data:image/png;base64,' + 'A' * (3 * 1024 * 1024)})

    assert not form.is_valid()
    assert 'signature' in form.errors


def test_a_signature_already_on_file_is_not_demanded_again():
    """Returning to the step via Back must not ask them to sign a second time."""
    form = _form(already_uploaded=['signature'])

    assert form.is_valid(), form.errors


def test_the_signature_is_stored_as_a_file_not_as_an_answer():
    form = _form({'signature_drawn': SIGNATURE_DATA_URL})
    assert form.is_valid(), form.errors

    assert 'signature' not in form.storable_answers()
    assert [key for key, _ in form.uploads()] == ['signature']


def test_a_drawn_signature_is_stored_on_an_opaque_background():
    """A transparent PNG of near-black strokes is invisible on anything dark.

    The pad's backing store has no background, so the page composites the
    strokes onto white before posting. Guarding the decode side here: whatever
    arrives must still be a real PNG, and the browser-side compositing is
    covered by the end-to-end run.
    """
    form = _form({'signature_drawn': SIGNATURE_DATA_URL})
    assert form.is_valid(), form.errors

    upload = form.cleaned_data['signature']
    upload.seek(0)
    assert upload.read().startswith(b'\x89PNG\r\n\x1a\n')


def test_the_pad_composites_onto_white_before_posting():
    """A transparent PNG of near-black strokes is invisible on anything dark.

    The compositing runs in the browser, so this guards the one thing a Django
    test can: that the shared pad script still does it. Deleting
    `exportSignature()` used to leave the whole suite green.
    """
    from django.template.loader import render_to_string

    script = render_to_string('shared/signature_pad.html')

    assert 'exportSignature' in script
    assert "fillStyle = '#ffffff'" in script
    assert 'fillRect' in script
    # and the raw canvas export must not be what gets posted
    assert "hidden.value = (signed && !picked) ? exportSignature() : ''" in script
    assert "toDataURL('image/png')" in script.split('function exportSignature')[1]


def test_every_step_template_that_can_render_a_pad_includes_the_script():
    """A step template rendering the shared field partial without the script
    would show a pad that accepts strokes and posts nothing."""
    import pathlib

    for name in ('employee_form', 'candidate_mapping', 'hr_verification'):
        path = pathlib.Path(f'/app/templates/{name}/step.html')
        body = path.read_text()
        assert "employee_form/partials/field.html" in body, name
        assert "shared/signature_pad.html" in body, name
