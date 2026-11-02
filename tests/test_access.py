"""The sandbox every read goes through: roots, real paths and the size cap."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest

from foam_verify import access
from foam_verify.study import assess_study, load_study

STUDIES = Path(__file__).resolve().parent.parent / "studies"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """root/inside.txt, and outside/secret.txt next to root."""
    (tmp_path / "root").mkdir()
    (tmp_path / "outside").mkdir()
    (tmp_path / "root" / "inside.txt").write_text("in")
    (tmp_path / "outside" / "secret.txt").write_text("secret")
    return tmp_path


def box(root: Path, max_bytes: int = 1000) -> access.Sandbox:
    return access.make_sandbox([root], max_bytes)


def test_without_a_sandbox_reads_go_anywhere(tree: Path) -> None:
    assert access.current() is None
    assert access.read_text(tree / "outside" / "secret.txt") == "secret"
    assert access.checked(tree / "root" / ".." / "outside") == (tree / "outside").resolve()


def test_inside_the_roots_reads_as_usual_and_the_sandbox_ends_with_the_block(tree: Path) -> None:
    with access.sandbox(box(tree / "root")) as b:
        assert access.current() is b
        assert access.read_text(tree / "root" / "inside.txt") == "in"
        assert access.read_head(tree / "root" / "inside.txt", 1) == b"i"
    assert access.current() is None


def test_dot_dot_cannot_leave_the_roots(tree: Path) -> None:
    escape = tree / "root" / ".." / "outside" / "secret.txt"
    with access.sandbox(box(tree / "root")), pytest.raises(access.AccessError, match="outside"):
        access.read_text(escape)


def test_a_symlinked_file_that_leads_outside_is_refused(tree: Path) -> None:
    link = tree / "root" / "link.txt"
    link.symlink_to(tree / "outside" / "secret.txt")
    with access.sandbox(box(tree / "root")):
        with pytest.raises(access.AccessError, match="link.txt is outside") as err:
            access.read_text(link)
        assert "secret" not in str(err.value)  # the message names the link, not the target
        with pytest.raises(access.AccessError, match="link.txt is outside"):
            access.read_head(link, 10)


def test_a_symlinked_folder_that_leads_outside_is_refused(tree: Path) -> None:
    (tree / "root" / "dir").symlink_to(tree / "outside", target_is_directory=True)
    with access.sandbox(box(tree / "root")):
        with pytest.raises(access.AccessError):
            access.checked(tree / "root" / "dir")
        with pytest.raises(access.AccessError):
            access.read_text(tree / "root" / "dir" / "secret.txt")


def test_a_symlink_that_stays_inside_is_fine(tree: Path) -> None:
    (tree / "root" / "alias.txt").symlink_to(tree / "root" / "inside.txt")
    with access.sandbox(box(tree / "root")):
        assert access.read_text(tree / "root" / "alias.txt") == "in"


def test_files_above_the_cap_are_refused_whole(tree: Path) -> None:
    big = tree / "root" / "big.txt"
    big.write_text("x" * 101)
    with access.sandbox(box(tree / "root", max_bytes=100)):
        with pytest.raises(access.FileTooLarge, match="larger than 100 bytes"):
            access.read_bytes(big)
        # A lower cap from the caller applies too, and a higher one cannot lift the sandbox's.
        with pytest.raises(access.FileTooLarge, match="larger than 50 bytes"):
            access.read_bytes(big, max_bytes=50)
        with pytest.raises(access.FileTooLarge, match="larger than 100 bytes"):
            access.read_bytes(big, max_bytes=500)
    assert len(access.read_bytes(big)) == 101  # no cap outside the sandbox


def test_the_cap_counts_decompressed_bytes(tree: Path) -> None:
    packed = tree / "root" / "zeros.gz"
    with gzip.open(packed, "wb") as fh:
        fh.write(b"0" * 10_000)  # about 50 bytes on disk
    assert packed.stat().st_size < 100
    with access.sandbox(box(tree / "root", max_bytes=1000)):
        with pytest.raises(access.FileTooLarge):
            access.read_bytes(packed)
        assert access.read_head(packed, 4) == b"0000"


def test_make_sandbox_checks_its_inputs(tree: Path) -> None:
    with pytest.raises(ValueError, match="not a folder"):
        access.make_sandbox([tree / "root" / "inside.txt"], 10)
    with pytest.raises(ValueError, match="at least one root"):
        access.make_sandbox([], 10)
    with pytest.raises(ValueError, match="positive"):
        access.make_sandbox([tree / "root"], 0)
    assert access.make_sandbox([tree / "root" / ".."], 10).roots == (tree.resolve(),)


def test_a_study_cannot_read_through_a_symlink_out_of_the_sandbox(tmp_path: Path) -> None:
    # The duct study, with the finest level's owner file swapped for a link to a file outside.
    root, outside = tmp_path / "root", tmp_path / "outside"
    study = root / "duct"
    shutil.copytree(STUDIES / "duct", study, ignore=shutil.ignore_patterns("build"))
    outside.mkdir()
    owner = study / "n160" / "constant" / "polyMesh" / "owner"
    shutil.move(owner, outside / "owner")
    owner.symlink_to(outside / "owner")
    assert assess_study(load_study(study)).levels[0].cells == 160**2  # fine without a sandbox
    with access.sandbox(box(root, 2**26)), pytest.raises(access.AccessError, match="outside"):
        assess_study(load_study(study))
    with access.sandbox(box(tmp_path, 2**26)):  # the same study, both folders allowed
        assert assess_study(load_study(study)).levels[0].cells == 160**2
