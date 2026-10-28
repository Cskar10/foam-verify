"""The OpenFOAM dictionary reader: syntax, macros, includes and skipped lists."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from foam_verify.foamdict import (
    LIST_KEY,
    FoamDict,
    FoamDictError,
    FoamList,
    Item,
    canonical,
    display,
    flatten,
    parse,
    read_dict,
    skipped,
    switch,
)

HEADER = """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //
"""


def binary_header(arch: str) -> str:
    return (
        "FoamFile { version 2.0; format binary; class volScalarField; "
        f'arch "{arch}"; object p; }}\n'
    )


def last(d: FoamDict, key: str) -> Item:
    """The last item of a primitive entry."""
    value = d[key]
    assert isinstance(value, tuple)
    return value[-1]


# --- syntax -------------------------------------------------------------------------------


def test_words_with_brackets_comments_and_sub_dictionaries() -> None:
    d = parse(
        HEADER
        + """
ddtSchemes { default steadyState; }   /* a block
comment */
divSchemes
{
    default         none;   // a line comment
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
"""
    )
    flat = flatten(d)
    assert flat["FoamFile/object"] == ("fvSchemes",)
    assert flat["ddtSchemes/default"] == ("steadyState",)
    assert flat["divSchemes/default"] == ("none",)
    assert flat["divSchemes/div(phi,U)"] == ("bounded", "Gauss", "linearUpwind", "grad(U)")
    assert flat["divSchemes/div((nuEff*dev2(T(grad(U)))))"] == ("Gauss", "linear")


def test_lists_dimension_sets_strings_and_regex_keys() -> None:
    d = parse(
        """
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (0 0 0);
"(U|k|epsilon)" { solver smoothSolver; }
libs            ("libmyBCs.so");
boundary        ( inlet { type patch; faces ((0 1 2 3)); } );
"""
    )
    assert d["dimensions"] == (FoamList(("0", "1", "-1", "0", "0", "0", "0"), open="["),)
    assert d["internalField"] == ("uniform", FoamList(("0", "0", "0")))
    assert isinstance(d['"(U|k|epsilon)"'], FoamDict)
    assert d["libs"] == (FoamList(('"libmyBCs.so"',)),)
    (boundary,) = d["boundary"]
    assert isinstance(boundary, FoamList)
    assert boundary.items[0] == "inlet" and isinstance(boundary.items[1], FoamDict)


def test_repeated_entries_override_and_dictionaries_merge() -> None:
    d = parse("a 1; a 2; s { x 1; y 1; } s { y 2; }")
    assert flatten(d) == {"a": ("2",), "s/x": ("1",), "s/y": ("2",)}


def test_a_file_holding_a_list() -> None:
    d = parse(HEADER + "(\n(0.1 0.2 0.3)\n(0.4 0.5 0.6)\n);\n")
    (positions,) = d[LIST_KEY]
    assert isinstance(positions, FoamList) and len(positions.items) == 2
    counted = parse(HEADER + "2\n(\n(0 0 0)\n(1 1 1)\n)\n")
    assert counted[LIST_KEY] == (
        FoamList((FoamList(("0", "0", "0")), FoamList(("1", "1", "1"))), count=2),
    )


# --- lists that depend on the mesh ----------------------------------------------------------


def test_counted_uniform_and_typed_lists() -> None:
    d = parse(
        """
faces           4(0 1 2 3);
internalField   nonuniform List<scalar>
3
(
1
2
3
)
;
inlet           nonuniform List<vector> 2((1 0 0) (2 0 0));
same            nonuniform List<scalar> 400{0.5};
after           1;
"""
    )
    assert d["faces"] == (FoamList(("0", "1", "2", "3"), count=4),)
    assert d["internalField"] == (
        "nonuniform",
        "List<scalar>",
        FoamList((), count=3, skipped="scalar"),
    )
    assert last(d, "inlet") == FoamList((), count=2, skipped="vector")
    assert last(d, "same") == FoamList(("0.5",), open="{", count=400)
    assert d["after"] == ("1",)
    assert skipped(d["internalField"]) and not skipped(d["faces"]) and not skipped(d["same"])


def test_binary_lists_are_skipped_by_length() -> None:
    # The raw bytes look like brackets, comments and ends of entries; only the length counts.
    noise = ')/*;"{}('.encode("latin-1")
    scalars = binary_header("LSB;label=32;scalar=64") + (
        "internalField nonuniform List<scalar> 3(" + (noise * 3).decode("latin-1") + ");\n"
        "uniformList nonuniform List<scalar> 7{" + noise.decode("latin-1") + "};\n"
        "after 1;\n"
    )
    d = parse(scalars)
    assert last(d, "internalField") == FoamList((), count=3, skipped="scalar")
    assert last(d, "uniformList") == FoamList((), open="{", count=7, skipped="scalar")
    assert d["after"] == ("1",)
    vectors = binary_header("LSB;label=32;scalar=32") + (
        "value nonuniform List<vector> 2(" + (noise * 3).decode("latin-1") + ");\nafter 2;\n"
    )
    assert parse(vectors)["after"] == ("2",)


REAL = Path(__file__).parent / "data" / "fields_v2512"


@pytest.mark.parametrize(
    ("path", "kind"),
    [("binary/U", "vector"), ("binary/p", "scalar"), ("compressed/U.gz", "vector")],
)
def test_real_v2512_fields_binary_and_compressed(path: str, kind: str) -> None:
    # OpenFOAM's own output: the cell values are skipped, the boundary conditions read.
    d = read_dict(REAL / path)
    flat = flatten(d)
    assert flat["internalField"] == (
        "nonuniform",
        f"List<{kind}>",
        FoamList((), count=400, skipped=kind),
    )
    assert flat["boundaryField/frontAndBack/type"] == ("empty",)
    if kind == "vector":
        assert flat["boundaryField/movingWall/value"] == ("uniform", FoamList(("1", "0", "0")))
        assert flat["boundaryField/fixedWalls/type"] == ("noSlip",)


def test_a_binary_list_of_the_wrong_length_is_an_error() -> None:
    text = binary_header("LSB;label=32;scalar=64") + "v nonuniform List<scalar> 2(12345678);\n"
    with pytest.raises(FoamDictError, match="does not end with"):
        parse(text, name="0/p")


# --- macros, includes and directives ----------------------------------------------------------


def test_macros_expand_from_the_enclosing_scopes() -> None:
    d = parse(
        """
velocity        (10 0 0);
solvers
{
    p       { solver GAMG; tolerance 1e-6; relTol 0.1; }
    pFinal  { $p; relTol 0; }
    U       { solver smoothSolver; tolerance $..p.tolerance; }
}
inlet           { value uniform $velocity; solver $:solvers/p/solver; }
unknown         $nothing;
"""
    )
    flat = flatten(d)
    assert flat["solvers/pFinal/solver"] == ("GAMG",)
    assert flat["solvers/pFinal/tolerance"] == ("1e-6",)
    assert flat["solvers/pFinal/relTol"] == ("0",)
    assert flat["solvers/U/tolerance"] == ("1e-6",)
    assert flat["inlet/value"] == ("uniform", FoamList(("10", "0", "0")))
    assert flat["inlet/solver"] == ("GAMG",)
    assert flat["unknown"] == ("$nothing",)


def test_includes_are_followed_inside_the_root_only(tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "0" / "include").mkdir(parents=True)
    (case / "0" / "include" / "initialConditions").write_text("flowVelocity (20 0 0);\n")
    (case / "system").mkdir()
    (case / "system" / "common").write_text(
        HEADER.replace("object      fvSchemes", "object      common") + "pressure 0;\n"
    )
    (tmp_path / "outside").write_text("secret 1;\n")
    (case / "0" / "U").write_text(
        HEADER
        + """
#include "include/initialConditions"
#include "<system>/common"
#include "../../outside"
#includeIfPresent "include/missing"
#includeEtc "caseDicts/setConstraintTypes"
internalField uniform $flowVelocity;
"""
    )
    d = read_dict(case / "0" / "U")
    assert d["internalField"] == ("uniform", FoamList(("20", "0", "0")))
    assert d["pressure"] == ("0",)
    header = d["FoamFile"]  # the file's own header, not the included file's
    assert isinstance(header, FoamDict) and header["object"] == ("fvSchemes",)
    assert "secret" not in d and '#include "../../outside"' in d
    assert '#includeEtc "caseDicts/setConstraintTypes"' in d
    assert not any("missing" in key for key in d)
    assert '#include "include/initialConditions"' in parse(
        '#include "include/initialConditions"\n'
    )  # a string has no root: nothing is followed


def test_other_directives_and_code_are_kept_as_written() -> None:
    d = parse(
        """
Aref            #eval{ $lRef*0.004 };
nx              #calc "$a * 2";
code
#{
    Info<< "})(;" << endl;
#};
#codeStream
{
    code #{ os << 1; #};
}
#inputMode merge
"""
    )
    assert d["Aref"] == ("#eval{ $lRef*0.004 }",)
    assert d["nx"] == ("#calc", '"$a * 2"')
    assert d["code"] == ('#{\n    Info<< "})(;" << endl;\n#}',)
    (block,) = d["#codeStream"]
    assert isinstance(block, FoamDict) and block["code"] == ("#{ os << 1; #}",)
    assert "#inputMode merge" in d


# --- files and errors ---------------------------------------------------------------------------


def test_gzip_and_the_size_cap(tmp_path: Path) -> None:
    path = tmp_path / "system" / "fvSolution.gz"
    path.parent.mkdir()
    path.write_bytes(gzip.compress(b"a 1;\n"))
    assert read_dict(path) == {"a": ("1",)}
    with pytest.raises(FoamDictError, match="larger than 3 bytes"):
        read_dict(path, max_bytes=3)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("a { b 1;", r"f:1: end of file inside a dictionary"),
        ("a\n(\n1 2", r"f:3: end of file inside a list"),
        ('a "unterminated;', r"f:1: unterminated string"),
        ("a 1;\n}\n", r"f:2: unexpected '}'"),
        ("a #{ code", r"f:1: unterminated #\{"),
    ],
)
def test_errors_name_the_file_and_line(text: str, message: str) -> None:
    with pytest.raises(FoamDictError, match=message):
        parse(text, name="f")


# --- comparing values -----------------------------------------------------------------------------


def test_canonical_compares_meaning_not_spelling() -> None:
    a = parse("x 1e-3; s yes; d { b 2; a 1; } l 3(1 2 3);")
    b = parse("x 0.001; s on; d { a 1.0; b 2; } l (1 2 3);")
    assert canonical(a) == canonical(b)
    assert canonical(parse("x 1;")) != canonical(parse("x 2;"))
    two = parse("v nonuniform List<scalar> 2(1 2);")
    three = parse("v nonuniform List<scalar> 3(4 5 6);")
    assert canonical(two) == canonical(three)  # mesh-dependent: by element type only
    assert canonical(two) != canonical(parse("v nonuniform List<vector> 2((1 0 0) (2 0 0));"))
    assert canonical(two) != canonical(parse("v uniform 1;"))


def test_display_and_switch() -> None:
    d = parse(
        "a uniform (1 0 0); b nonuniform List<vector> 400((0 0 0)); s off; e { };"
        + "long ("
        + " ".join(["1"] * 100)
        + ");"
    )
    assert display(d["a"]) == "uniform (1 0 0)"
    assert display(d["b"]) == "nonuniform List<vector> 400(...)"
    assert display(d["e"]) == "{ }"
    assert len(display(d["long"])) == 80 and display(d["long"]).endswith("...")
    assert switch(d["s"]) is False and switch(d["a"]) is None and switch(None) is None
