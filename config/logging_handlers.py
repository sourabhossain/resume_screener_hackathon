"""
File logging helpers — predictable daily filenames aligned with Django timezone.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from django.utils import timezone


class DateNamedFileHandler(logging.Handler):
    """
    Append to logs/app_YYYY-MM-DD.log using timezone.localdate() (respects TIME_ZONE).

    Unlike TimedRotatingFileHandler, each dated file normally holds only lines from that
    calendar day (stream switches at the first log record after local midnight).
    """

    def __init__(
        self,
        logs_dir: str | Path,
        prefix: str = 'app',
        backup_count: int = 30,
        encoding: str = 'utf-8',
    ) -> None:
        logging.Handler.__init__(self)
        self.logs_dir = Path(logs_dir)
        self.prefix = prefix
        self.backup_count = backup_count
        self.encoding = encoding
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._stream = None
        self._current_date_key: str | None = None
        self._lock = threading.RLock()

    def _path_for_date_key(self, date_key: str) -> Path:
        return self.logs_dir / f'{self.prefix}_{date_key}.log'

    def _purge_old_files(self) -> None:
        pattern = f'{self.prefix}_*.log'
        files = sorted(
            self.logs_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in files[self.backup_count :]:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _ensure_stream(self) -> None:
        date_key = timezone.localdate().isoformat()
        if date_key == self._current_date_key and self._stream is not None:
            return
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        self._current_date_key = date_key
        path = self._path_for_date_key(date_key)
        self._stream = open(path, 'a', encoding=self.encoding)
        self._purge_old_files()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._lock:
                self._ensure_stream()
                msg = self.format(record)
                if self._stream is None:
                    return
                self._stream.write(msg + '\n')
                self.flush()
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        with self._lock:
            if self._stream:
                self._stream.flush()

    def close(self) -> None:
        with self._lock:
            if self._stream:
                self._stream.close()
                self._stream = None
            self._current_date_key = None
        logging.Handler.close(self)
