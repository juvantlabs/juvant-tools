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

## What it generates (v0.2)

Fifteen files conforming to the spec's "Required files" + "CI requirements"
sections, plus six `.gitkeep` markers — 21 outputs total.

### Documentation + license

- `README.md` — project overview, install, **`## Environment variables`**
  (parsed by the CI README-accuracy check), tool list (placeholder).
- `LICENSE` — MIT, copyright Juvant Srls (canonical).
- `ARCHITECTURE.md` — design rationale stub with sections to fill.
- `CHANGELOG.md` — Keep a Changelog format, `[Unreleased]` initialized.
- `CONTRIBUTING.md` — pointer to handbook + repo-specific quick path.
- `SECURITY.md` — disclosure channels + SLOs (per handbook SECURITY-template.md).
- `.github/CODEOWNERS` — placeholder.

### Build + tooling

- `package.json` — name, scripts (`build`, `dev`, `lint`, `typecheck`,
  `test`, `test:unit`, `test:integration`, `audit`), deps
  (`@modelcontextprotocol/sdk ^1.25.2`), dev-deps (vitest, ESLint v9,
  TypeScript-ESLint, `@vitest/coverage-v8`).
- `tsconfig.json` — strict TypeScript config (literal).
- `eslint.config.mjs` — flat config (ESLint v9), `no-console: ["error",
  { allow: ["error", "warn"] }]` enforces stdout discipline at lint time.
- `vitest.config.ts` — coverage v8, ≥80% line/function/branch/statement
  thresholds (per handbook spec).
- `.gitignore` — comprehensive (secrets, key material, build artifacts).

### CI

- `.github/workflows/ci.yml` — runs on PR + push to `main`, covers all
  8 spec checks:
  1. ESLint
  2. `tsc --noEmit`
  3. Unit tests + coverage (vitest)
  4. Integration tests (skipped if no `VENDOR_SANDBOX_TOKEN` secret)
  5. `npm audit --audit-level=moderate`
  6. **Stdout discipline grep** — `console.log\(` in `src/` → fail
  7. **Dead-code grep** — exported `validate*/sanitize*/guard*/enforce*/assert*` symbols must be imported elsewhere in `src/`
  8. **README env-var accuracy** — every var in README's `## Environment
     variables` section must be referenced via `process.env.X` in `src/`
     (placeholders containing `<>` and short acronyms are skipped)
- `.github/workflows/publish.yml` — runs on tag push (`v*.*.*`), gated by
  the `production` GitHub Environment for manual approval, publishes to
  npm with provenance using `NPM_TOKEN` repo secret.

### Source skeleton

- `src/index.ts` — minimal MCP server stub with stdio transport,
  tools list/dispatch handlers, reads `process.env.MCP_SERVER_LOG_LEVEL`
  for log-level configuration. **No `console.log` anywhere** (neither
  code nor comments) — keeps CI green from the first commit.

Plus empty directories with `.gitkeep`:

- `src/auth/`, `src/tools/`, `src/client/`, `src/types/`
- `tests/unit/`, `tests/integration/`

## Validation

After scaffolding, the tool checks that all 15 required files exist.
Failure raises `ClickException` and the partially-scaffolded directory
is left in place for inspection.

The 3 CI grep checks are designed to pass on a fresh scaffold (the README
documents `<VENDOR>_API_KEY` as a placeholder — the `<>` skips it — and
`MCP_SERVER_LOG_LEVEL` which `src/index.ts` actually reads). They start
gating real changes the moment you wire up a real env var or export a
security helper.

## Conformance to spec

The templates in `templates/` are pre-baked from the handbook
`mcp-server.md` spec at the time of writing. If the spec evolves, the
scaffolder must be updated. CI in `juvantlabs/juvant-tools` validates
template-vs-spec alignment.

## Next steps after scaffolding

The CLI prints a "Next steps" block. Summary:

```bash
cd <vendor>-mcp-server
npm install                          # generates package-lock.json
git init && git add -A && git commit -m "init: scaffold per handbook mcp-server.md"
gh repo create juvantlabs/<vendor>-mcp-server --public --description "<description>"
git remote add origin git@github.com:juvantlabs/<vendor>-mcp-server.git
git branch -M main && git push -u origin main
```

In the GitHub repo settings:

- Enable branch protection on `main` (require CI green + 1 review).
- Configure the `production` environment with required reviewers, so
  the publish workflow needs manual approval before tagging to npm.
- Add `NPM_TOKEN` as a repository secret (used by
  `.github/workflows/publish.yml`).

Then implement tools per the spec's "Tool design" + "Anti-patterns"
sections.
