# juvant-tools

OSS-shareable utility scripts, dev tools, and CLI helpers for the Juvant OS
ecosystem. Toolbox repository per the
[`docs/repo-types/toolbox.md`](https://github.com/juvantlabs/handbook/blob/main/docs/repo-types/toolbox.md)
spec at `juvantlabs/handbook`.

## Status

**v0.1 — first tool shipped.** The
[`scaffold mcp-server`](juvant_tools/scaffolders/mcp_server/README.md)
command generates a new `juvantlabs/<vendor>-mcp-server` repo skeleton
conforming to the [handbook MCP server spec](https://github.com/juvantlabs/handbook/blob/main/docs/repo-types/mcp-server.md).
More tools land via PR.

## Quick start

This repo is currently distributed via `git clone` (no PyPI publish
yet — see [Distribution](#distribution) below).

```bash
git clone https://github.com/juvantlabs/juvant-tools.git
cd juvant-tools

# (optional) virtual env
python3 -m venv .venv
source .venv/bin/activate

# install in editable mode
pip install -e .

# run a scaffolder interactively
juvant-tools scaffold mcp-server
# or, without installing the entrypoint:
python -m juvant_tools.cli scaffold mcp-server
```

## Tools shipped

### Packaged — `juvant-tools <subcommand>` (after `pip install -e .`)

| Tool | Category | What it does |
|---|---|---|
| [`scaffold mcp-server`](juvant_tools/scaffolders/mcp_server/README.md) | MCP server scaffolding | Generates a new `juvantlabs/<vendor>-mcp-server` repo skeleton from the [handbook MCP server spec](https://github.com/juvantlabs/handbook/blob/main/docs/repo-types/mcp-server.md). All 15 required files (docs + license + tooling + CI workflows + ESLint flat config + vitest config), wired to pass the 8 spec-mandated CI checks (incl. stdout discipline, dead-code grep, README env-var accuracy) on a fresh scaffold. |

### Standalone scripts — `python3 <category>/<script>.py`

| Script | Category | What it does |
|---|---|---|
| [`audio/video_to_audio.py`](audio/README.md) | Audio | ffmpeg wrapper — extract audio from a video file as WAV / MP3 / AAC / raw PCM 16k mono. |
| [`audio/raw_pcm_to_wav.py`](audio/README.md) | Audio | Convert a raw PCM capture (8-byte header + Int16 samples) into a WAV file with silence trim, mono downmix, and resampling. |
| [`stt/azure_stt.py`](stt/README.md) | STT | Transcribe any audio/video file using Azure Speech SDK with optional speaker diarization. Streams results to file as they arrive. |
| [`cdp/http_spy.py`](cdp/README.md) | CDP | Chrome DevTools Protocol HTTP spy — capture HTTP requests/responses on a live browser tab, filtered by URL substring, with UUID/ID extraction from JSON bodies. |
| [`cdp/websocket_spy.py`](cdp/README.md) | CDP | Chrome DevTools Protocol WebSocket spy — capture every WS frame (incl. iframe sub-targets) on a live browser tab. UTF-8 / JSON auto-decode; hex fallback for binary. |

## Repo layout — packaged vs. unpackaged tools

The repo deliberately holds two kinds of tool side-by-side:

- **`juvant_tools/`** (snake_case, the importable Python package) — code
  we want versioned, importable, and invokable as `juvant-tools <subcmd>`.
  Goes through `pyproject.toml`, earns CHANGELOG entries + semver, and
  (eventually) a PyPI release. Today: just the scaffolders. Future
  packaged tools land here as new subcommands.
- **Top-level category directories** (e.g. `observability/`, `audit/`,
  `disclosure-helpers/` — none yet, illustrative) — standalone scripts /
  quick helpers run directly via `git clone` + `./category/script`. No
  semver, no install step, possibly in different languages (bash, TS,
  etc.). When a script earns import-by-others or subcommand status, it
  migrates into `juvant_tools/`.

The repo name (`juvant-tools`, kebab-case) and the package name
(`juvant_tools`, snake_case) deliberately differ — standard Python
disambiguation between "the project" and "the import path".

This dual layout is codified in the
[handbook toolbox spec](https://github.com/juvantlabs/handbook/blob/main/docs/repo-types/toolbox.md#packaged-vs-unpackaged-tools--the-dual-layout).

## Scope

This toolbox is **OSS-shareable**, meaning:

- Generic across products (no Hardys-specific or other product
  coupling).
- Useful to external Juvant OS adopters as well as Juvant Srls itself.
- Distributed under MIT.

For **product-specific** dev tools (e.g. tools that only make sense
when running against Hardys-internal endpoints), see
[`juvantio/hardys-dev-tools`](https://github.com/juvantio/hardys-dev-tools)
(private) — separate repo, separate license posture, separate scope.

## Planned tools (when the need arises)

| Category | Example tools | Status |
|---|---|---|
| Juvant OS instance hygiene | Lint a per-company instance against the framework's spec; audit `agent_tool_matrix` vs. `MCP_INVENTORY.md`; check for surviving placeholders | not yet |
| Library / framework / toolbox scaffolding | Same pattern as `scaffold mcp-server` for the other repo types | not yet |
| Audit + disclosure helpers | Run a static-analysis audit on a community MCP server; produce a draft audit report per the [`audit-report-template.md`](https://github.com/juvantlabs/handbook/blob/main/docs/security/audit-report-template.md) | not yet |
| Local dev workflow | Helpers for testing hooks against a local Turso file, simulating webhook deliveries against `juvant-os` instances, etc. | not yet |

These are illustrative. Tools enter the toolbox when there's a real
need — no premature creation.

## Distribution

**Currently `git clone` + editable install only.** No PyPI publish yet.
The package name `juvant-tools` is reserved on PyPI but unpublished
until the toolbox earns it (≥ 3 distinct users / production-critical /
weekly use, per the [handbook toolbox spec](https://github.com/juvantlabs/handbook/blob/main/docs/repo-types/toolbox.md#promote-to-registry)).

## Development

```bash
pip install -e ".[dev]"
pytest                # run tests
ruff check .          # lint
mypy juvant_tools     # type-check
```

## Contributing

See [handbook CONTRIBUTING.md](https://github.com/juvantlabs/handbook/blob/main/CONTRIBUTING.md)
for the meta contributor guide. Quick summary for this repo:

1. Open an issue describing the tool you'd like to add — confirm fit
   for the toolbox category (vs. library / MCP server / framework).
2. PR the tool with: source, README entry in the matching subdirectory,
   `--help` invocation, smoke test if applicable.
3. CI runs lint + smoke test + tracked-secret detector. Light bar
   for tooling vs. library/MCP-server formality.

## Anti-patterns

The toolbox spec at the handbook calls out the failure mode that bit
the predecessor `juvantio/juvant-dev-tools` (renamed
[`juvantio/hardys-dev-tools`](https://github.com/juvantio/hardys-dev-tools)
on 2026-05-03 because its content was 100% Hardys-specific despite the
"juvant" naming). Concrete rules to keep this repo OSS-shareable:

- No business-confidential strings (counterparty names, internal URLs,
  product-specific feature names).
- No hardcoded credentials or tokens.
- No coupling to a single private product.

When a tool grows product-specific, **split it**: extract the generic
core to this repo, leave the product-specific extension at
`juvantio/<product>-dev-tools`.

## License

[MIT](LICENSE).
