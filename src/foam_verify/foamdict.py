"""A small reader for OpenFOAM dictionaries: enough to compare settings entry by entry.

parse() and read_dict() turn a dictionary into nested FoamDicts. Each entry is a
sub-dictionary or the sequence of items that make up its value: words, numbers, strings,
lists and dimension sets. The reader follows OpenFOAM's syntax without evaluating it:

- comments, quoted strings, regex keys such as "(U|k).*" and words with brackets such as
  div(phi,U) are read as OpenFOAM reads them;
- $name, $:name, $..name and paths such as $a/b or $a.b are expanded when they refer to an
  entry read earlier; otherwise they stay as written;
- #include, #includeIfPresent and #sinclude are followed when the file lies inside root.
  Every other directive (#includeEtc, #includeFunc, #calc, #codeStream, ...) and verbatim
  #{ ... #} code are kept as text, so they compare by what is written;
- a typed list such as nonuniform List<vector> 400(...) is skipped, in ASCII and binary
  files, and kept as its element type and length: values that depend on the mesh are not read;
- files ending in .gz are decompressed. Text is decoded as Latin-1, one character per byte.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from . import access

DEFAULT_MAX_BYTES = 64 * 2**20
MAX_INCLUDE_DEPTH = 8
# The key under which a file that holds a list, not a dictionary, keeps its list.
LIST_KEY = "<list>"


class FoamDictError(ValueError):
    """A dictionary that cannot be read; the message names the file and the line."""


class FoamDict(dict[str, "Entry"]):
    """One dictionary level: keyword to sub-dictionary or value items, in file order."""


@dataclass(frozen=True)
class FoamList:
    """A list in a value: ( ... ), a dimension set [ ... ] or a uniform list N{ ... }.

    count is the length written before the list, if any. A typed list such as List<vector>
    is not read: its items are empty and skipped names the element type.
    """

    items: tuple[Item, ...]
    open: str = "("
    count: int | None = None
    skipped: str | None = None


Item: TypeAlias = "str | FoamList | FoamDict"
Entry: TypeAlias = "FoamDict | tuple[Item, ...]"

_SPACE = re.compile(r"(?:\s+|//[^\n]*|/\*.*?(?:\*/|\Z))+", re.S)
_INLINE = re.compile(r"[ \t]+")
_COMMENT = re.compile(r"//.*|/\*.*?\*/")
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"', re.S)
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_WORD = re.compile(r'[^\s;{}"\[\]()/]+')
_PAREN = re.compile(r"[()]")
_INTEGER = re.compile(r"\d+")
_TYPED = re.compile(r"List<(\w+)>")
_ARCH = re.compile(r"(label|scalar)\s*=\s*(\d+)")
_ARG = re.compile(r'"([^"]*)"|(\S+)')
_PUNCT = frozenset("{}()[];")
_AFTER_NUMBER = frozenset(' \t\r\n\f\v;{}()[]"/')
_CLOSE = {"(": ")", "[": "]", "{": "}"}
_WIDTH = {
    "scalar": 1,
    "vector": 3,
    "symmTensor": 6,
    "tensor": 9,
    "sphericalTensor": 1,
    "vector2D": 2,
    "symmTensor2D": 3,
    "tensor2D": 4,
}
_INCLUDES = frozenset({"#include", "#includeIfPresent", "#sinclude"})
_TRUE = frozenset({"true", "on", "yes"})
_FALSE = frozenset({"false", "off", "no"})


def parse(
    text: str,
    *,
    name: str = "<string>",
    case: str | Path | None = None,
    root: str | Path | None = None,
) -> FoamDict:
    """Parse dictionary text. #include is followed only inside root, relative to case."""
    folder = None if case is None else Path(case)
    reader = _Reader(
        text,
        name,
        directory=folder,
        case=folder,
        root=None if root is None else Path(root).resolve(),
        max_bytes=DEFAULT_MAX_BYTES,
    )
    return reader.document()


def read_dict(
    path: str | Path,
    *,
    case: str | Path | None = None,
    root: str | Path | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> FoamDict:
    """Read a dictionary file. #include is followed inside root, by default the case folder.

    The case folder holds system/, constant/ and 0/. By default it is the parent of the
    file's folder when that is one of the three, and the file's folder otherwise.
    """
    file = Path(path)
    if case is None:
        in_case = file.parent.name in ("system", "constant", "0")
        case = file.parent.parent if in_case else file.parent
    folder = Path(case)
    reader = _Reader(
        _read_text(file, max_bytes),
        str(file),
        directory=file.parent,
        case=folder,
        root=Path(root if root is not None else folder).resolve(),
        max_bytes=max_bytes,
    )
    return reader.document()


def _read_text(path: Path, max_bytes: int) -> str:
    try:
        return access.read_text(path, "latin-1", max_bytes)
    except access.FileTooLarge as exc:
        raise FoamDictError(str(exc)) from exc


def _store(into: FoamDict, key: str, value: Entry) -> None:
    """Add an entry; a sub-dictionary given twice is merged, as OpenFOAM does."""
    old = into.get(key)
    if isinstance(old, FoamDict) and isinstance(value, FoamDict):
        for k, v in value.items():
            _store(old, k, v)
    else:
        into[key] = value


def _find(scope: FoamDict, name: str) -> Entry | None:
    if name in scope:
        return scope[name]
    for sep in ("/", "."):
        if sep in name:
            head, _, rest = name.partition(sep)
            sub = scope.get(head)
            if isinstance(sub, FoamDict):
                return _find(sub, rest)
    return None


def _typed(items: list[Item]) -> str | None:
    """The element type when the last item read is List<type>."""
    if items and isinstance(items[-1], str):
        match = _TYPED.fullmatch(items[-1])
        if match:
            return match.group(1)
    return None


class _Reader:
    def __init__(
        self,
        text: str,
        name: str,
        *,
        directory: Path | None,
        case: Path | None,
        root: Path | None,
        max_bytes: int,
        depth: int = 0,
        scopes: list[FoamDict] | None = None,
    ) -> None:
        self.text = text
        self.pos = 0
        self.name = name
        self.directory = directory
        self.case = case
        self.root = root
        self.max_bytes = max_bytes
        self.depth = depth
        self.scopes: list[FoamDict] = [] if scopes is None else scopes
        self.binary = False
        self.label_bytes = 4
        self.scalar_bytes = 8

    def error(self, message: str) -> FoamDictError:
        line = self.text.count("\n", 0, self.pos) + 1
        return FoamDictError(f"{self.name}:{line}: {message}")

    # --- tokens ---------------------------------------------------------------------------

    def skip(self) -> None:
        match = _SPACE.match(self.text, self.pos)
        if match:
            self.pos = match.end()

    def token(self) -> str | None:
        self.skip()
        text, pos = self.text, self.pos
        if pos >= len(text):
            return None
        char = text[pos]
        if char in _PUNCT:
            self.pos = pos + 1
            return char
        if char == '"':
            string = _STRING.match(text, pos)
            if string is None:
                raise self.error("unterminated string")
            self.pos = string.end()
            return string.group()
        if text.startswith("#{", pos):
            end = text.find("#}", pos + 2)
            if end < 0:
                raise self.error("unterminated #{ ... #} block")
            self.pos = end + 2
            return text[pos : self.pos]
        if text.startswith("${", pos):
            self.pos = self.after_brace(pos + 1)
            return text[pos : self.pos]
        number = _NUMBER.match(text, pos)
        if number and (number.end() == len(text) or text[number.end()] in _AFTER_NUMBER):
            self.pos = number.end()
            return number.group()
        word = self.word()
        if word == "#eval":  # #eval{ expression } is kept whole, as written
            inline = _INLINE.match(text, self.pos)
            start = inline.end() if inline else self.pos
            if text.startswith("{", start):
                self.pos = self.after_brace(start)
                return text[pos : self.pos]
        return word

    def word(self) -> str:
        """A word, with brackets inside it as in div(phi,U); it ends at an unmatched ')'."""
        text = self.text
        start = pos = self.pos
        depth = 0
        while pos < len(text):
            part = _WORD.match(text, pos)
            if part:
                pos = part.end()
                continue
            char = text[pos]
            if char == "(":
                depth += 1
            elif char == ")" and depth:
                depth -= 1
            elif char != "/" or text.startswith(("//", "/*"), pos):
                break
            pos += 1
        if pos == start:
            raise self.error(f"unexpected character {text[pos]!r}")
        self.pos = pos
        return text[start:pos]

    def after_brace(self, pos: int) -> int:
        depth = 0
        for index in range(pos, len(self.text)):
            char = self.text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if not depth:
                    return index + 1
        raise self.error("unterminated ${ ... }")

    # --- dictionaries -----------------------------------------------------------------------

    def document(self) -> FoamDict:
        top = FoamDict()
        self.scopes.append(top)
        self.entries(top, None)
        return top

    def sub_dict(self) -> FoamDict:
        """The entries up to the '}' that closes a '{' just read."""
        sub = FoamDict()
        self.scopes.append(sub)
        try:
            self.entries(sub, "}")
        finally:
            self.scopes.pop()
        return sub

    def entries(self, into: FoamDict, close: str | None) -> None:
        while True:
            tok = self.token()
            if tok is None:
                if close is None:
                    return
                raise self.error(f"end of file inside a dictionary: missing {close!r}")
            if tok == close:
                return
            if tok == ";":
                continue
            if tok == "(" and close is None:  # a file that holds a list, not a dictionary
                _store(into, LIST_KEY, (FoamList(self.list_items(")")),))
            elif tok in _PUNCT:
                raise self.error(f"unexpected {tok!r}")
            elif close is None and _INTEGER.fullmatch(tok) and self.list_follows():
                _store(into, LIST_KEY, (self.counted(int(tok), None),))
            elif tok.startswith("#") and not tok.startswith("#{"):
                self.directive(tok, into)
            elif not (tok.startswith("$") and self.merge(tok, into)):
                self.entry(tok, into)

    def entry(self, key: str, into: FoamDict) -> None:
        self.skip()
        value: Entry
        if self.text.startswith("{", self.pos):
            self.pos += 1
            value = self.sub_dict()
        else:
            value = self.value()
        if key == "FoamFile" and isinstance(value, FoamDict):
            if self.depth or len(self.scopes) > 1:
                return  # the header of an included file
            self.header(value)
        _store(into, key, value)

    def header(self, header: FoamDict) -> None:
        fmt = header.get("format")
        self.binary = isinstance(fmt, tuple) and fmt[:1] == ("binary",)
        arch = header.get("arch")
        if isinstance(arch, tuple) and arch and isinstance(arch[0], str):
            for kind, bits in _ARCH.findall(arch[0]):
                if kind == "label":
                    self.label_bytes = int(bits) // 8
                else:
                    self.scalar_bytes = int(bits) // 8

    def merge(self, tok: str, into: FoamDict) -> bool:
        """$name as an entry: copy the entries of the dictionary it names, if it names one."""
        found = self.lookup(tok)
        if not isinstance(found, FoamDict):
            return False
        for key, value in copy.deepcopy(found).items():
            _store(into, key, value)
        self.skip()
        if self.text.startswith(";", self.pos):
            self.pos += 1
        return True

    def lookup(self, tok: str) -> Entry | None:
        name = tok[1:]
        if name.startswith("{"):
            if name.startswith("{{") or not name.endswith("}"):
                return None  # ${{ expression }} is evaluated by OpenFOAM, not here
            name = name[1:-1]
        if name.startswith(":"):
            chain = self.scopes[:1]
            name = name[1:]
        elif name.startswith("."):
            dots = len(name) - len(name.lstrip("."))
            index = len(self.scopes) - dots
            if index < 0:
                return None
            chain = [self.scopes[index]]
            name = name[dots:]
        else:
            chain = self.scopes[::-1]
        if not name:
            return None
        for scope in chain:
            found = _find(scope, name)
            if found is not None:
                return found
        return None

    def directive(self, name: str, into: FoamDict) -> None:
        """#include and friends are followed; any other directive is kept as an entry."""
        end = self.text.find("\n", self.pos)
        end = len(self.text) if end < 0 else end
        args = _COMMENT.sub("", self.text[self.pos : end]).strip().rstrip(";").strip()
        start = self.pos
        if not args or args.startswith("{"):  # #codeStream { ... }, the brace maybe below
            self.skip()
            if self.text.startswith("{", self.pos):
                self.pos += 1
                into[name] = (self.sub_dict(),)
                return
            self.pos = start
        self.pos = end
        if name in _INCLUDES and self.include(name, args, into):
            return
        into[f"{name} {args}" if args else name] = ()

    def include(self, name: str, args: str, into: FoamDict) -> bool:
        """Read an included file into `into`; False keeps the directive as written."""
        match = _ARG.match(args)
        path = self.resolve(match.group(1) or match.group(2)) if match else None
        if path is None or self.root is None:
            return False
        real = path.resolve()
        if not real.is_relative_to(self.root):
            return False
        if not real.is_file():
            return name != "#include"  # #includeIfPresent and #sinclude: nothing to read
        if self.depth >= MAX_INCLUDE_DEPTH:
            raise self.error(f"{name} nested more than {MAX_INCLUDE_DEPTH} deep")
        reader = _Reader(
            _read_text(real, self.max_bytes),
            str(real),
            directory=real.parent,
            case=self.case,
            root=self.root,
            max_bytes=self.max_bytes,
            depth=self.depth + 1,
            scopes=self.scopes,
        )
        reader.entries(into, None)
        return True

    def resolve(self, target: str) -> Path | None:
        if self.case is not None:
            case = str(self.case)
            target = target.replace("${FOAM_CASE}", case).replace("$FOAM_CASE", case)
            for tag, sub in (("<case>", ""), ("<system>", "system"), ("<constant>", "constant")):
                if target.startswith(tag):
                    target = str(self.case / sub) + target[len(tag) :]
        if "$" in target or target.startswith("<"):
            return None
        path = Path(target)
        if not path.is_absolute():
            if self.directory is None:
                return None
            path = self.directory / path
        return path

    # --- values -----------------------------------------------------------------------------

    def value(self) -> tuple[Item, ...]:
        """The items of a primitive entry, up to its ';'."""
        items: list[Item] = []
        while True:
            tok = self.token()
            if tok is None or tok == ";":
                return tuple(items)
            if tok == "}":  # the enclosing dictionary closes without a final ';'
                self.pos -= 1
                return tuple(items)
            self.item(tok, items)

    def list_items(self, close: str) -> tuple[Item, ...]:
        items: list[Item] = []
        while True:
            tok = self.token()
            if tok is None:
                raise self.error(f"end of file inside a list: missing {close!r}")
            if tok == close:
                return tuple(items)
            if tok != ";":
                self.item(tok, items)

    def item(self, tok: str, items: list[Item]) -> None:
        if tok == "(":
            items.append(FoamList(self.list_items(")")))
        elif tok == "[":
            items.append(FoamList(self.list_items("]"), open="["))
        elif tok == "{":
            items.append(self.sub_dict())
        elif tok in (")", "]", "}"):
            raise self.error(f"unexpected {tok!r}")
        elif tok.startswith("$") and len(tok) > 1:
            found = self.lookup(tok)
            if isinstance(found, FoamDict):
                items.append(copy.deepcopy(found))
            elif found is not None:
                items.extend(found)
            else:
                items.append(tok)
        elif _INTEGER.fullmatch(tok) and self.list_follows():
            items.append(self.counted(int(tok), _typed(items)))
        else:
            items.append(tok)

    def list_follows(self) -> bool:
        self.skip()
        return self.text.startswith(("(", "{"), self.pos)

    def counted(self, n: int, kind: str | None) -> FoamList:
        """A list written with its length: N( ... ) or N{ value }; typed lists are skipped."""
        bracket = self.text[self.pos]
        self.pos += 1
        close = _CLOSE[bracket]
        if kind is None or (bracket == "{" and not self.binary):
            return FoamList(self.list_items(close), open=bracket, count=n)
        if self.binary:
            end = self.pos + (n if bracket == "(" else 1) * self.width(kind)
            if self.text[end : end + 1] != close:
                raise self.error(f"binary List<{kind}> of {n} does not end with {close!r}")
            self.pos = end + 1
        else:
            depth = 1
            for paren in _PAREN.finditer(self.text, self.pos):
                depth += 1 if paren.group() == "(" else -1
                if not depth:
                    self.pos = paren.end()
                    break
            else:
                raise self.error(f"end of file inside List<{kind}>")
        return FoamList((), open=bracket, count=n, skipped=kind)

    def width(self, kind: str) -> int:
        if kind == "label":
            return self.label_bytes
        if kind in _WIDTH:
            return _WIDTH[kind] * self.scalar_bytes
        raise self.error(f"cannot skip a binary List<{kind}>")


# --- comparing values ---------------------------------------------------------------------


def flatten(d: FoamDict, prefix: str = "") -> dict[str, Entry]:
    """Every value in d by its path of keys joined with '/'; empty sub-dictionaries stay."""
    out: dict[str, Entry] = {}
    for key, value in d.items():
        path = f"{prefix}/{key}" if prefix else key
        if isinstance(value, FoamDict) and value:
            out.update(flatten(value, path))
        else:
            out[path] = value
    return out


def canonical(value: Entry | Item) -> str:
    """A form for comparing values: numbers by value, switches as true or false,
    dictionaries in key order, list lengths dropped, skipped lists by element type only."""
    if isinstance(value, FoamDict):
        return "{" + " ".join(f"{k} {canonical(value[k])};" for k in sorted(value)) + "}"
    if isinstance(value, FoamList):
        if value.skipped is not None:
            return f"List<{value.skipped}>{value.open}...{_CLOSE[value.open]}"
        return value.open + " ".join(canonical(i) for i in value.items) + _CLOSE[value.open]
    if isinstance(value, tuple):
        return " ".join(canonical(i) for i in value)
    if _NUMBER.fullmatch(value):
        return repr(float(value))
    if value.lower() in _TRUE:
        return "true"
    if value.lower() in _FALSE:
        return "false"
    return value


def display(value: Entry | Item, limit: int = 80) -> str:
    """The value as written, shortened to limit characters."""
    text = _show(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _show(value: Entry | Item) -> str:
    if isinstance(value, FoamDict):
        inner = " ".join(f"{k} {_show(v)};" for k, v in value.items())
        return "{ " + inner + " }" if inner else "{ }"
    if isinstance(value, FoamList):
        count = "" if value.count is None else str(value.count)
        if value.skipped is not None:
            return f"{count}{value.open}...{_CLOSE[value.open]}"
        return count + value.open + " ".join(_show(i) for i in value.items) + _CLOSE[value.open]
    if isinstance(value, tuple):
        return " ".join(_show(i) for i in value)
    return value


def skipped(value: Entry | Item) -> bool:
    """Whether a value holds a typed list that was skipped rather than read."""
    if isinstance(value, FoamList):
        return value.skipped is not None or any(skipped(i) for i in value.items)
    if isinstance(value, FoamDict):
        return any(skipped(v) for v in value.values())
    if isinstance(value, tuple):
        return any(skipped(i) for i in value)
    return False


def switch(value: Entry | None) -> bool | None:
    """An OpenFOAM switch (true, on, yes; false, off, no) as a bool, or None."""
    if isinstance(value, tuple) and len(value) == 1 and isinstance(value[0], str):
        word = value[0].lower()
        if word in _TRUE:
            return True
        if word in _FALSE:
            return False
    return None
