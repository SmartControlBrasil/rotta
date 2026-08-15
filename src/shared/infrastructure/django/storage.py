from pathlib import PurePosixPath
from typing import BinaryIO

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateDocumentStorageAdapter:
    """Local private-document adapter for development and tests."""

    def __init__(self, storage: FileSystemStorage | None = None) -> None:
        self.storage = storage or FileSystemStorage(location=settings.PRIVATE_DOCUMENT_STORAGE_ROOT)

    def save(self, path: str, content: BinaryIO) -> str:
        return self.storage.save(self._safe_path(path), content)

    def delete(self, path: str) -> None:
        safe_path = self._safe_path(path)
        if self.storage.exists(safe_path):
            self.storage.delete(safe_path)

    def exists(self, path: str) -> bool:
        return self.storage.exists(self._safe_path(path))

    def open(self, path: str, mode: str = "rb") -> BinaryIO:
        if "w" in mode or "+" in mode or "a" in mode:
            raise ValueError("Document storage open() is read-only; use save() for writes.")
        return self.storage.open(self._safe_path(path), mode)

    def url(self, path: str) -> str:
        raise NotImplementedError("Private business documents do not expose permanent public URLs.")

    def _safe_path(self, path: str) -> str:
        normalized = PurePosixPath(path)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("Document storage path must be relative and stay inside storage root.")
        return normalized.as_posix()
