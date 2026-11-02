"""File access for the readers: one place that opens files, so that a server can confine them.

Every file foam-verify reads goes through read_bytes(), read_text() or read_head(), and every
folder it lists or globs through checked(). Outside a sandbox, as from the command line, these
read as usual, and the study reader's own rules apply (foam_verify.study: case folders and QoI
files inside the study). Inside sandbox(), which the MCP server sets around every tool call,
each path is resolved with its symlinks followed and must lie under one of the allowed roots,
and no file may be larger than the sandbox's max_bytes. A .gz file is capped by its
decompressed size.

The check resolves the path and then opens it, so a symlink swapped in between could escape it.
That race needs someone who can write inside the roots while a call runs, and the sandbox is not
meant to stop them: it stops a study, or a tool argument, from reaching outside the roots.
"""

from __future__ import annotations

import gzip
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


class AccessError(PermissionError):
    """A path outside the sandbox's roots, or a file above its size cap."""


class FileTooLarge(AccessError):
    """A file above the size cap."""


@dataclass(frozen=True)
class Sandbox:
    """Resolved folders the readers may read under, and the largest file they may read."""

    roots: tuple[Path, ...]
    max_bytes: int

    def allows(self, real: Path) -> bool:
        return any(real.is_relative_to(root) for root in self.roots)


_CURRENT: ContextVar[Sandbox | None] = ContextVar("foam_verify_sandbox", default=None)


def current() -> Sandbox | None:
    """The sandbox in force, or None outside one."""
    return _CURRENT.get()


def make_sandbox(roots: Iterable[str | Path], max_bytes: int) -> Sandbox:
    """A sandbox over existing folders, resolved; at least one, and max_bytes above zero."""
    resolved: list[Path] = []
    for root in roots:
        path = Path(root).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"root {root} is not a folder")
        resolved.append(path)
    if not resolved:
        raise ValueError("a sandbox needs at least one root")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    return Sandbox(tuple(resolved), max_bytes)


@contextmanager
def sandbox(box: Sandbox) -> Generator[Sandbox]:
    """Confine every read in this block, in this thread or task, to box."""
    token = _CURRENT.set(box)
    try:
        yield box
    finally:
        _CURRENT.reset(token)


def checked(path: str | Path) -> Path:
    """The real path of a file or folder about to be read or listed.

    Inside a sandbox it must lie under one of the roots; the error names the path as given, not
    where a symlink leads.
    """
    real = Path(path).resolve()
    box = _CURRENT.get()
    if box is not None and not box.allows(real):
        raise AccessError(f"{path} is outside the allowed roots")
    return real


def _cap(max_bytes: int | None) -> int | None:
    box = _CURRENT.get()
    caps = [c for c in (max_bytes, None if box is None else box.max_bytes) if c is not None]
    return min(caps) if caps else None


def read_bytes(path: str | Path, max_bytes: int | None = None) -> bytes:
    """A whole file, decompressed when its name ends in .gz.

    It may be at most max_bytes long, and inside a sandbox at most the sandbox's cap; a longer
    one raises FileTooLarge rather than being cut short.
    """
    real = checked(path)
    cap = _cap(max_bytes)
    opener = gzip.open if real.name.endswith(".gz") else open
    with opener(real, "rb") as stream:
        data = stream.read() if cap is None else stream.read(cap + 1)
    if cap is not None and len(data) > cap:
        raise FileTooLarge(f"{path}: larger than {cap} bytes")
    return data


def read_text(path: str | Path, encoding: str = "utf-8", max_bytes: int | None = None) -> str:
    return read_bytes(path, max_bytes).decode(encoding)


def read_head(path: str | Path, size: int) -> bytes:
    """The first size bytes of a file, decompressed when its name ends in .gz; never more."""
    real = checked(path)
    opener = gzip.open if real.name.endswith(".gz") else open
    with opener(real, "rb") as stream:
        return stream.read(size)
