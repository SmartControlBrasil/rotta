from __future__ import annotations

import hashlib
import mimetypes
import re
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}


@dataclass(frozen=True)
class ValidatedUpload:
    content: BytesIO
    safe_filename: str
    original_filename: str
    content_type: str
    content_hash: str
    size_bytes: int


def _max_upload_bytes() -> int:
    return int(getattr(settings, "DOCUMENT_UPLOAD_MAX_BYTES", 10 * 1024 * 1024))


def sanitize_original_filename(filename: str) -> str:
    basename = Path(filename or "document").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("._")
    return cleaned[:255] or "document"


def build_storage_filename(original_filename: str) -> str:
    extension = Path(sanitize_original_filename(original_filename)).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        extension = ".bin"
    return f"{uuid.uuid4().hex}{extension}"


def validate_upload_file(*, uploaded_file) -> ValidatedUpload:
    if uploaded_file is None:
        raise ValidationError({"file": "Arquivo é obrigatório."})

    original_filename = sanitize_original_filename(getattr(uploaded_file, "name", "document"))
    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError({"file": "Formato não permitido. Use PDF, JPEG ou PNG."})

    content = uploaded_file.read()
    size_bytes = len(content)
    if size_bytes <= 0:
        raise ValidationError({"file": "Arquivo vazio não é permitido."})
    if size_bytes > _max_upload_bytes():
        raise ValidationError({"file": "Arquivo excede o tamanho máximo permitido."})

    guessed_type = mimetypes.guess_type(original_filename)[0] or ""
    content_type = getattr(uploaded_file, "content_type", "") or guessed_type
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationError({"file": "Tipo MIME não permitido."})

    content_hash = hashlib.sha256(content).hexdigest()
    return ValidatedUpload(
        content=BytesIO(content),
        safe_filename=build_storage_filename(original_filename),
        original_filename=original_filename,
        content_type=content_type,
        content_hash=content_hash,
        size_bytes=size_bytes,
    )
