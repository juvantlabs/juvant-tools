"""MCP server scaffolder — `juvant-tools scaffold mcp-server`.

Reads the handbook docs/repo-types/mcp-server.md spec (in spirit; templates
are pre-baked from it at scaffolder build time) and generates a conforming
juvantlabs/<vendor>-mcp-server repo skeleton.

Surfaces:

- Pure function `scaffold_mcp_server_repo(...)` — deterministic, no I/O
  beyond the filesystem write, no `click` UX. Raises `ScaffoldError`
  subclasses on validation/runtime failure. Used by:
    - The CLI subcommand below (`juvant-tools scaffold mcp-server`)
    - The MCP server in `juvant_tools.mcp_server`

v0.2 generates all 15 required files documented in the spec, including
the CI workflow (lint + test + audit + 3 grep-based defense-in-depth
checks), the npm publish workflow (manual approval gate via GitHub
Environments), the ESLint flat config (with the no-console-log rule),
and the vitest config with the 80% coverage threshold from the spec.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import click
from jinja2 import Environment, FileSystemLoader, StrictUndefined

# Files written from templates (stripped of .j2 suffix on output).
TEMPLATE_FILES_J2 = {
    "README.md.j2",
    "LICENSE.j2",
    "package.json.j2",
    "ARCHITECTURE.md.j2",
    "CHANGELOG.md.j2",
    "CONTRIBUTING.md.j2",
    "SECURITY.md.j2",
    "src/index.ts.j2",
}

# Files copied verbatim (no Jinja substitution).
# Keys are paths under templates/, values are paths under the scaffolded repo.
# Some templates use a non-dotted name in templates/ to avoid Python packaging
# tools dropping hidden files from sdists/wheels (e.g. `gitignore` →
# `.gitignore`, `github/` → `.github/`).
LITERAL_FILES = {
    "tsconfig.json": "tsconfig.json",
    "gitignore": ".gitignore",
    "CODEOWNERS": ".github/CODEOWNERS",
    "github/workflows/ci.yml": ".github/workflows/ci.yml",
    "github/workflows/publish.yml": ".github/workflows/publish.yml",
    "eslint.config.mjs": "eslint.config.mjs",
    "vitest.config.ts": "vitest.config.ts",
}

# Directories that should exist in the output even if empty (with .gitkeep).
EMPTY_DIRS = (
    "src/auth",
    "src/tools",
    "src/client",
    "src/types",
    "tests/unit",
    "tests/integration",
)

# Required files used to validate the scaffold post-render.
REQUIRED_OUTPUT_FILES = (
    "README.md",
    "LICENSE",
    "package.json",
    "tsconfig.json",
    ".gitignore",
    "ARCHITECTURE.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    ".github/CODEOWNERS",
    ".github/workflows/ci.yml",
    ".github/workflows/publish.yml",
    "eslint.config.mjs",
    "vitest.config.ts",
    "src/index.ts",
)

VENDOR_RE = re.compile(r"^[a-z][a-z0-9-]*$")
VALID_SCOPES = ("read", "rw")


# =====================================================================
# Structured errors
# =====================================================================

class ScaffoldError(Exception):
    """Base for all scaffolder errors. `code` is a stable string identifier
    suitable for programmatic dispatch (e.g. by an MCP client / agent)."""
    code: str = "scaffold_error"


class InvalidVendorNameError(ScaffoldError):
    code = "invalid_vendor_name"


class InvalidScopeError(ScaffoldError):
    code = "invalid_scope"


class OutputPathExistsError(ScaffoldError):
    code = "output_path_exists"

    def __init__(self, output_path: Path):
        super().__init__(f"{output_path} already exists; refusing to overwrite")
        self.output_path = output_path


class TemplateMissingError(ScaffoldError):
    code = "template_missing"


class ScaffoldValidationError(ScaffoldError):
    """Post-render validation failure (required output file missing)."""
    code = "validation_failed"

    def __init__(self, missing: list[str]):
        super().__init__(f"Scaffold validation failed: missing {missing}")
        self.missing = missing


# =====================================================================
# Result
# =====================================================================

@dataclass
class ScaffoldResult:
    """Successful scaffold outcome."""
    output_path: Path
    repo_name: str
    files_written: list[str] = field(default_factory=list)


# =====================================================================
# Pure function — used by both CLI and MCP entry points
# =====================================================================

def scaffold_mcp_server_repo(
    vendor: str,
    scope: str,
    description: str,
    output_dir: Path | None = None,
) -> ScaffoldResult:
    """Scaffold a juvantlabs/<vendor>-mcp-server repo skeleton.

    Args:
        vendor: lowercase, hyphenated identifier (e.g. "finom",
            "aruba-fattura"). Must match `^[a-z][a-z0-9-]*$`.
        scope: "read" or "rw". MCP scope qualifier.
        description: one-line description of the vendor's API.
        output_dir: where to write the new repo. If None, writes to
            `./{vendor}-mcp-server` relative to current working directory.

    Returns:
        ScaffoldResult with output_path, repo_name, files_written.

    Raises:
        InvalidVendorNameError: vendor doesn't match the pattern.
        InvalidScopeError: scope is not "read" or "rw".
        OutputPathExistsError: target directory already exists.
        TemplateMissingError: a literal template file is missing on disk
            (corrupted install).
        ScaffoldValidationError: post-render check found a required file
            missing on disk.
    """
    if not VENDOR_RE.match(vendor):
        raise InvalidVendorNameError(
            "vendor must be lowercase, alphanumeric + hyphens, starting with a letter"
        )
    if scope not in VALID_SCOPES:
        raise InvalidScopeError(f"scope must be one of {list(VALID_SCOPES)}; got {scope!r}")

    repo_name = f"{vendor}-mcp-server"
    output_path = output_dir if output_dir is not None else Path.cwd() / repo_name

    if output_path.exists():
        raise OutputPathExistsError(output_path)

    today = date.today()
    context = {
        "vendor": vendor,
        "vendor_titled": " ".join(p.capitalize() for p in vendor.split("-")),
        "vendor_description": description,
        "scope": scope,
        "repo_name": repo_name,
        "package_name": f"@juvantlabs/{repo_name}",
        "year": today.year,
        "current_date": today.isoformat(),
    }

    templates_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    output_path.mkdir(parents=True)
    written: list[str] = []

    # 1. Render Jinja templates
    for rel_str in TEMPLATE_FILES_J2:
        template = env.get_template(rel_str)
        rendered = template.render(**context)
        out_rel = Path(rel_str).with_suffix("")  # strip .j2
        out_full = output_path / out_rel
        out_full.parent.mkdir(parents=True, exist_ok=True)
        out_full.write_text(rendered)
        written.append(str(out_rel))

    # 2. Copy literal files (no Jinja substitution)
    for src_rel, dst_rel in LITERAL_FILES.items():
        src = templates_dir / src_rel
        if not src.exists():
            raise TemplateMissingError(f"Template file missing: {src_rel}")
        dst = output_path / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text())
        written.append(dst_rel)

    # 3. Create empty directories with .gitkeep
    for empty_dir in EMPTY_DIRS:
        gitkeep = output_path / empty_dir / ".gitkeep"
        gitkeep.parent.mkdir(parents=True, exist_ok=True)
        gitkeep.touch()
        written.append(f"{empty_dir}/.gitkeep")

    # 4. Validate required outputs
    missing = [f for f in REQUIRED_OUTPUT_FILES if not (output_path / f).exists()]
    if missing:
        raise ScaffoldValidationError(missing)

    return ScaffoldResult(
        output_path=output_path,
        repo_name=repo_name,
        files_written=written,
    )


# =====================================================================
# CLI thin wrapper
# =====================================================================

@click.command()
@click.option(
    "--vendor",
    prompt="Vendor name (lowercase, hyphenated — e.g. finom, aruba-fattura, m365-graph)",
    help="Vendor identifier used in the repo name and package name.",
)
@click.option(
    "--scope",
    default="read",
    show_default=True,
    type=click.Choice(["read", "rw"]),
    help="MCP scope qualifier — read or read+write.",
)
@click.option(
    "--description",
    prompt="One-line vendor description (used in README + package.json)",
    help="Short description of what the vendor's API exposes.",
)
@click.option(
    "--output",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory (default: ./<vendor>-mcp-server).",
)
def scaffold_mcp_server(
    vendor: str,
    scope: str,
    description: str,
    output: Path | None,
) -> None:
    """Scaffold a new juvantlabs/<vendor>-mcp-server repo.

    Conforms to handbook docs/repo-types/mcp-server.md. Generates all
    15 required files plus 6 .gitkeep markers for the empty directory
    skeleton (src/auth, src/tools, src/client, src/types, tests/unit,
    tests/integration).
    """
    try:
        result = scaffold_mcp_server_repo(
            vendor=vendor,
            scope=scope,
            description=description,
            output_dir=output,
        )
    except InvalidVendorNameError as e:
        raise click.BadParameter(str(e), param_hint="--vendor") from e
    except InvalidScopeError as e:
        raise click.BadParameter(str(e), param_hint="--scope") from e
    except OutputPathExistsError as e:
        raise click.ClickException(str(e)) from e
    except ScaffoldError as e:
        raise click.ClickException(str(e)) from e

    # Report + next-steps
    click.echo("")
    click.echo(f"✓ Scaffolded {result.repo_name} at {result.output_path}")
    click.echo(f"  ({len(result.files_written)} files)")
    click.echo("")
    click.echo("Next steps:")
    click.echo(f"  cd {result.output_path}")
    click.echo("  npm install              # generates package-lock.json")
    click.echo('  git init && git add -A && git commit -m "init: scaffold per handbook mcp-server.md"')
    click.echo(f"  gh repo create juvantlabs/{result.repo_name} --public \\")
    click.echo(f'    --description "{description}"')
    click.echo(f"  git remote add origin git@github.com:juvantlabs/{result.repo_name}.git")
    click.echo("  git branch -M main && git push -u origin main")
    click.echo("")
    click.echo("In GitHub repo settings:")
    click.echo("  - Enable branch protection on `main` (require CI green + 1 review).")
    click.echo("  - Configure the `production` environment with required reviewers,")
    click.echo("    so the publish workflow needs manual approval before tagging to npm.")
    click.echo("  - Add NPM_TOKEN as a repository secret (used by .github/workflows/publish.yml).")
    click.echo("")
    click.echo("Then implement your tools in src/tools/, wire auth in src/auth/,")
    click.echo("and follow the handbook spec at:")
    click.echo("  https://github.com/juvantlabs/handbook/blob/main/docs/repo-types/mcp-server.md")


if __name__ == "__main__":
    sys.exit(scaffold_mcp_server())
