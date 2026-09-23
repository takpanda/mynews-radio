"""Shared, atomically updated storage for Codex OAuth token pairs."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class CodexTokenStore:
    """Coordinate Codex token rotation between API and cron processes.

    The lock is held while a refresh request is made by the caller. This is
    intentional: Codex refresh tokens are single-use and two processes must
    not refresh the same pair concurrently.
    """

    def __init__(self, path: str):
        self._path = Path(path).expanduser()
        self._lock_path = self._path.with_name(f"{self._path.name}.lock")

    @contextmanager
    def locked(self) -> Iterator[dict[str, str] | None]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as lock_file:
            os.chmod(self._lock_path, 0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield self._read_unlocked()
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def read(self) -> dict[str, str] | None:
        with self.locked() as tokens:
            return tokens

    def load_or_initialize(self, access_token: str, refresh_token: str) -> dict[str, str] | None:
        """Read the canonical pair, initializing it from env only once."""
        with self.locked() as tokens:
            if tokens is not None:
                return tokens
            if access_token and refresh_token:
                tokens = {"access_token": access_token, "refresh_token": refresh_token}
                self._write_unlocked(tokens)
                return tokens
            return None

    def write_unlocked(self, access_token: str, refresh_token: str) -> None:
        """Persist a pair while the caller holds ``locked()``."""
        self._write_unlocked({"access_token": access_token, "refresh_token": refresh_token})

    def _read_unlocked(self) -> dict[str, str] | None:
        try:
            with self._path.open(encoding="utf-8") as token_file:
                payload: Any = json.load(token_file)
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            return None
        if not access_token.strip() or not refresh_token.strip():
            return None
        return {"access_token": access_token.strip(), "refresh_token": refresh_token.strip()}

    def _write_unlocked(self, tokens: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.", dir=self._path.parent, text=True
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as token_file:
                os.chmod(temporary_name, 0o600)
                json.dump(tokens, token_file, ensure_ascii=False, separators=(",", ":"))
                token_file.write("\n")
                token_file.flush()
                os.fsync(token_file.fileno())
            os.replace(temporary_name, self._path)
            os.chmod(self._path, 0o600)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
