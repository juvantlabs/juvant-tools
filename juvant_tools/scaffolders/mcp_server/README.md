# Scaffolder — `mcp-server`

Generates a new `juvantlabs/<vendor>-mcp-server` repo skeleton conforming
to the
[handbook docs/repo-types/mcp-server.md](https://github.com/juvantlabs/handbook/blob/main/docs/repo-types/mcp-server.md)
spec.

## Usage

Interactive (recommended for manual scaffolding):

```bash
python -m juvant_tools.cli scaffold mcp-server
```

You'll be prompted for:

- `vendor` — lowercase, hyphenated identifier (e.g. `finom`,
  `aruba-fattura`, `m365-graph`). Used in the repo name and package
  name (`juvantlabs/<vendor>-mcp-server`, `@juvantlabs/<vendor>-mcp-server`).
- `scope` — MCP scope qualifier: `read` (default) or `rw`.
- `description` — one-line description of what the vendor's API exposes.
- `output` — output directory (default: `./<vendor>-mcp-server`).

Flag-driven (CI-friendly):

```bash
python -m juvant_tools.cli scaffold mcp-server \
  --vendor finom \
  --scope read \
  --description "Finom Partner API banking read-only MCP server" \
  --output ./finom-mcp-server
```

## What it generates (v0.1)

Eleven files conforming to the spec's "Required files" section:

- `README.md` — project overview, install, configuration, tool list (placeholder)
- `LICENSE` — MIT, copyright Juvant Srls (canonical)
- `package.json` — name, scripts, deps (`@modelcontextprotocol/sdk ^1.25.2`)
- `tsconfig.json` — strict TypeScript config
- `.gitignore` — comprehensive (secrets, key material, build artifacts)
- `ARCHITECTURE.md` — design rationale stub with sections to fill
- `CHANGELOG.md` — Keep a Changelog format, `[Unreleased]` initialized
- `CONTRIBUTING.md` — pointer to handbook + repo-specific quick path
- `SECURITY.md` — disclosure channels + SLOs (per handbook SECURITY-template.md)
- `.github/CODEOWNERS` — placeholder
- `src/index.ts` — minimal MCP server entry stub with handler skeletons

Plus empty directories with `.gitkeep`:

- `src/auth/`, `src/tools/`, `src/client/`, `src/types/`
- `tests/unit/`, `tests/integration/`

## What it does NOT generate (v0.1)

Two files documented in the spec but pending v0.2 of the scaffolder:

- `.github/workflows/ci.yml` — CI lint + test + audit + dead-code grep
  + stdout discipline check
- `.github/workflows/publish.yml` — npm publish on tag
- `eslint.config.mjs` — strict TypeScript ESLint with no-console-log rule

These are substantial templates that warrant care + a v0.1 dogfood pass.
v0.2 of the scaffolder will produce them.

## Validation

After scaffolding, the tool checks that all 11 required files exist.
Failure raises `ClickException` and the partially-scaffolded directory
is left in place for inspection.

For `tsc --noEmit` validation + `npm install` dry-run, see v0.2.

## Conformance to spec

The templates in `templates/` are pre-baked from the handbook
`mcp-server.md` spec at the time of writing. If the spec evolves, the
scaffolder must be updated. CI in `juvantlabs/juvant-tools` validates
template-vs-spec alignment.

## Next steps after scaffolding

The CLI prints a "Next steps" block. Summary:

```bash
cd <vendor>-mcp-server
npm install
git init && git add -A && git commit -m "init: scaffold per handbook mcp-server.md"
gh repo create juvantlabs/<vendor>-mcp-server --public --description "<description>"
git remote add origin git@github.com:juvantlabs/<vendor>-mcp-server.git
git branch -M main && git push -u origin main
```

Then implement tools per the spec's "Tool design" + "Anti-patterns"
sections.
