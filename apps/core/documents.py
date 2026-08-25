"""How a stored answer or upload is described to a template.

The three form apps keep their answers in JSON and their uploads against a
question key, and each was growing its own copy of "is this an image?", "what
URL renders it inline?" and "how does a stored date read?". They belong in one
place: the upload rules encode what `serve_protected_media` will actually agree
to serve inline, and a copy that drifts from it renders a dead link or an <img>
the server refuses.
"""
from datetime import date


def display_date(raw):
    """An ISO date stored in a JSON answer, rendered the way a person reads one.

    Answers are JSON, so a date comes back as '2026-08-25'. Left alone it reaches
    the review page raw, sitting next to prose -- and an unparseable value
    (hand-edited, or left over from an older schema) still has to show rather
    than blow the page up.
    """
    try:
        return date.fromisoformat(str(raw)).strftime('%d %b %Y')
    except (TypeError, ValueError):
        return raw


class StoredDocumentMixin:
    """Display helpers for a model with `file`, `original_name` and `size_bytes`."""

    IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.png', '.webp')

    @property
    def extension(self) -> str:
        name = self.original_name or self.file.name or ''
        return name.rsplit('.', 1)[-1].lower() if '.' in name else ''

    @property
    def kind(self) -> str:
        """How the viewer should render this: 'image', 'pdf' or 'file'.

        'file' covers doc/docx, which no browser displays — those are offered as
        a download instead of being put in a dead iframe.
        """
        name = (self.original_name or self.file.name or '').lower()
        if name.endswith(self.IMAGE_SUFFIXES):
            return 'image'
        if name.endswith('.pdf'):
            return 'pdf'
        return 'file'

    @property
    def is_image(self) -> bool:
        """Whether a review page can show this inline.

        A signature is only useful as a picture: as a filename it says nothing,
        and it is the one thing on these forms a reader has to actually look at.
        """
        return self.kind == 'image'

    @property
    def view_url(self) -> str:
        """URL that renders in the browser rather than downloading.

        `serve_protected_media` only honours inline for formats it considers
        safe, so this falls back to the plain (download) URL for anything else.
        """
        if self.kind == 'file':
            return self.file.url
        return f'{self.file.url}?inline=1'

    @property
    def size_display(self) -> str:
        size = self.size_bytes or 0
        if size >= 1024 * 1024:
            return f'{size / (1024 * 1024):.1f} MB'
        if size >= 1024:
            return f'{size / 1024:.0f} KB'
        return f'{size} B'
