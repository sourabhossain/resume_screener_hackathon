"""How a stored upload is described to a template.

Three apps store candidate and HR documents against a question key, and each was
growing its own copy of "is this an image?" and "what URL renders it inline?".
The rules belong in one place: they encode what `serve_protected_media` will
actually agree to serve inline, and a copy that drifts from it renders a dead
link or an <img> the server refuses.
"""


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
