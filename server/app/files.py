"""Private local adapter. Business code depends only on data_access.FileStorage."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import BinaryIO, Iterator

from .data_access import FileStorage, StagedFile, StorageUnavailable


class _LocalStagedFile:
    def __init__(self, storage: LocalFileStorage, path: Path, stream: BinaryIO):
        self._storage = storage
        self._path = path
        self._stream = stream

    @property
    def stream(self) -> BinaryIO:
        return self._stream

    def publish(self, key: str) -> bool:
        try:
            self._stream.flush()
            os.fsync(self._stream.fileno())
            self._stream.close()
            return self._storage._publish(key, self._path)
        except OSError:
            raise StorageUnavailable('文件发布失败') from None


class LocalFileStorage:
    """Immutable local keys. Existing content is never replaced; paths stay private."""

    def __init__(self, root: str | Path):
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._tmp = self._root / 'tmp'
        self._tmp.mkdir(exist_ok=True)

    def _path(self, key: str) -> Path:
        relative = PurePosixPath(key)
        if not key or '\\' in key or ':' in key or relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid storage key')
        path = (self._root / key).resolve()
        if path == self._root or not path.is_relative_to(self._root):
            raise ValueError('Invalid storage key')
        return path

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def open_read(self, key: str) -> BinaryIO:
        return self._path(key).open('rb')

    @contextmanager
    def stage(self) -> Iterator[StagedFile]:
        try:
            descriptor, name = tempfile.mkstemp(prefix='staging-', suffix='.part', dir=self._tmp)
        except OSError:
            raise StorageUnavailable('无法创建暂存文件') from None
        staged_path = Path(name)
        try:
            with os.fdopen(descriptor, 'w+b') as stream:
                yield _LocalStagedFile(self, staged_path, stream)
        finally:
            staged_path.unlink(missing_ok=True)

    def _publish(self, key: str, source: Path) -> bool:
        destination = self._path(key)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, destination)
            source.unlink()
            return True
        except FileExistsError:
            return False
        except OSError:
            raise StorageUnavailable('文件发布失败') from None

    def write(self, key: str, data: bytes) -> bool:
        with self.stage() as staged:
            staged.stream.write(data)
            return staged.publish(key)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def ping(self) -> None:
        with self.stage():
            pass