# MCP server: tools, setup and the sandbox

`foam-verify mcp` serves foam-verify's checks to an MCP client, such as Claude Code, Claude
Desktop or an IDE, over stdio. The client starts the server and calls its tools; each tool reads
a grid study and returns JSON with the verdict, the numbers behind it and the reasons. The
tools only read, and only under the folders the server was started with.

The server needs the `mcp` extra, the official MCP Python SDK, pinned below version 2 (version 2
removed the `FastMCP` server this one is built on). Nothing else in foam-verify needs it.

## Setup

From a clone of the repository, give the server one or more folders to read under with
`--root`:

```console
$ uv run --directory /path/to/foam-verify --extra mcp foam-verify mcp --root /path/to/studies
```

A client starts that command itself. In Claude Code:

```console
$ claude mcp add foam-verify -- uv run --directory /path/to/foam-verify --extra mcp \
    foam-verify mcp --root /path/to/studies
```

In a client configured by JSON, such as Claude Desktop:

```json
{
  "mcpServers": {
    "foam-verify": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/foam-verify", "--extra", "mcp",
               "foam-verify", "mcp", "--root", "/path/to/studies"]
    }
  }
}
```

`--root` may be repeated. `--max-file-mb` sets the largest file a tool reads, 64 MiB by default.
The server writes only the protocol to stdout; its log goes to stderr.

## Tools

Every tool takes a `study` (except `list_studies`): the study's folder or its `study.toml`,
absolute or relative to a root. A relative path goes to the first root that has it. Results
give the study's absolute `path`.

| Tool | Returns |
|---|---|
| `list_studies` | every folder holding a `study.toml` up to four folders below each root, with its name, levels, QoIs and number of references; a study that cannot be read is listed with the error |
| `study_summary` | the study as `study.toml` defines it: refined directions, refinement scope, grid sequence, formal order, the levels with their cell counts, each QoI's definition and each reference |
| `grid_convergence` | for every QoI or one (`qoi`): its value on each level and the grid study's result, the convergence type, observed order, Richardson extrapolation, U and band, every triplet, the reasons and warnings ([gci.md](gci.md)) |
| `iterative_convergence` | for every QoI or one: the iterative verdict on each level from the QoI's own history, and whether iterative error contaminates the grid study ([iterative.md](iterative.md)) |
| `settings_consistency` | whether the levels differ only in the mesh, with every difference level by level ([consistency.md](consistency.md)) |
| `compare_reference` | for every QoI or one: each reference in `study.toml` against the finest-grid value, E = S - D with its outcome and reasons ([compare.md](compare.md)) |
| `verification_report` | the full report: the verdict on every QoI with each check behind it, what stops a clean pass, and the reference comparisons; the JSON of `foam-verify report --json` with the study's `path`, or with `format` `markdown` the Markdown ([report.md](report.md)) |

`verification_report` answers the main question, whether a value is converged and
mesh-independent; the other tools give its parts. Every tool is marked read-only, idempotent
and closed-world in its MCP annotations. An error, such as a study that cannot be read or a
path outside the roots, comes back as a tool error with the reason.

## The sandbox

The server keeps to its roots on every call, whatever the study or the arguments say:

- **Roots.** The `--root` folders are resolved when the server starts, and each must exist.
- **Real paths.** Every file a tool reads and every folder it lists is resolved, symlinks
  followed, and must lie under a root (`foam_verify.access`); otherwise the call fails with
  "outside the allowed roots". A study argument with `..` that leaves the roots, an absolute
  path elsewhere, or a symlinked study that leads outside fails the same way, with the same
  message whether or not anything exists there.
- **Inside a study** the study reader is stricter still: a case folder or QoI file must lie
  inside the study and a QoI file pattern must be relative, a settings file that links outside
  it is not read (a warning that blocks a clean pass), and `#include` is followed only inside
  it.
- **Size cap.** No file larger than the cap is read; a larger one is refused whole rather than
  cut short. A `.gz` file is capped by its decompressed size.
- **`list_studies`** looks at most four folders below each root, skips hidden folders, does not
  follow symlinked folders and lists at most 200 studies.
- **Read-only.** No tool writes a file, starts a process or uses the network. The server never
  calls the report writer of `foam-verify report --output`.

Outside the server, from the command line or as a library, foam-verify reads as before: the
sandbox applies only inside the server's tool calls.

## Tests

`tests/test_server.py` calls every tool through the SDK's in-memory client, as an MCP client
would, and checks each result against the library's: the reports in both forms on all three
committed studies, the grid, iterative, consistency and comparison results, and the summaries.
Then it tries to get out:

- every study tool with `..`, an absolute path elsewhere, `~` and the repository root as the
  study;
- a symlinked study, and studies that reach outside through a symlinked manifest, case folder,
  mesh header, settings folder, QoI table or `postProcessing` folder, a level path or QoI file
  pattern in the manifest, or an absolute pattern; each is refused, and a secret planted outside
  never appears in a result;
- a settings file that links outside, and an `#include` of a file outside: neither is read;
- a file above the size cap, refused whole;
- every tool on a copy of the cavity with process starts and network connections made to fail:
  each tool works, and the copy is byte for byte the same afterwards.

`tests/test_access.py` tests the sandbox itself: roots, `..`, symlinked files and folders, the
cap and compressed files.

## Limits

- The sandbox resolves a path and then opens it. Someone who can write inside the roots while a
  call runs could swap a symlink in between; the sandbox stops a study or an argument from
  reaching outside the roots, not a concurrent writer.
- A tool call runs in the server's process and reassesses the study each time, so it takes as
  long as `foam-verify report` on the same study; nothing is cached.
- Error messages name paths under the roots, absolute.
