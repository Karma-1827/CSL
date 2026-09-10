from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


def ensure_demo_pdf_exists(relative_path):
    """Write a minimal valid one-page PDF to `relative_path` under MEDIA_ROOT if nothing
    is there yet, and return that same path unchanged.

    Demo seed commands historically pointed `QualificationDocument.file` at a bare string
    path (e.g. "qualifications/demo-proof.pdf") without ever writing real file content —
    this worked for tests (which use their own throwaway media) but leaves a human
    clicking preview/download in a real local dev browser hitting a FileNotFoundError,
    since the path was never backed by an actual file. Using a fixed path (rather than the
    model's randomized upload_to()) keeps re-running the seed idempotent: the file is
    written once and reused, instead of piling up a new orphaned upload every run.
    """
    if not default_storage.exists(relative_path):
        from pypdf import PdfWriter
        from io import BytesIO

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = BytesIO()
        writer.write(buffer)
        default_storage.save(relative_path, ContentFile(buffer.getvalue()))
    return relative_path
