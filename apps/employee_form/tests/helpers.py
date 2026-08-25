"""Shared test data for the employee_form tests."""
import base64

from django.core.files.uploadedfile import SimpleUploadedFile

# A real 1x1 PNG. Real bytes rather than a placeholder because uploads are
# checked against their magic bytes, and a drawn signature is decoded and put
# through that same check.
PNG_1PX_BASE64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8'
    'z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)

# What the signature canvas posts when the candidate signs instead of uploading.
SIGNATURE_DATA_URL = f'data:image/png;base64,{PNG_1PX_BASE64}'


def signature_upload(name='signature.png'):
    """A signature the candidate picked as a file rather than drawing."""
    return SimpleUploadedFile(
        name, base64.b64decode(PNG_1PX_BASE64), content_type='image/png'
    )
