"""MCP server scaffolder — `juvant-tools scaffold mcp-server`.

Reads the handbook docs/repo-types/mcp-server.md spec (in spirit; templates
are pre-baked from it at scaffolder build time) and generates a conforming
juvantlabs/<vendor>-mcp-server repo skeleton.

v0.1 ships 11 of the 13 required files documented in the spec; v0.2 will
add CI workflow + ESLint config.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import click
from jinja2 import Environment, FileSystemLoader, StrictUndefined

# Files written from templates (stripped of .j2 suffix on output).
# Files NOT in this list are copied verbatim (no Jinja).
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

LITERAL_FILES = {
    "tsconfig.json",
    "gitignore",  # renamed to .gitignore on output
    "CODEOWNERS",  # placed under .github/
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
    "src/index.ts",
)

VENDOR_RE = re.compile(r"^[a-z][a-z0-9-]*$")


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

    Conforms to handbook docs/repo-types/mcp-server.md. Generates 11 of
    the 13 required files (CI workflow + ESLint config land in v0.2).
    """
    if not VENDOR_RE.match(vendor):
        raise click.BadParameter(
            "vendor must be lowercase, alphanumeric + hyphens, starting with a letter"
        )

    repo_name = f"{vendor}-mcp-server"
    output_path = output if output is not None else Path.cwd() / repo_name

    if output_path.exists():
        raise click.ClickException(f"{output_path} already exists; refusing to overwrite")

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
    for literal in LITERAL_FILES:
        src = templates_dir / literal
        if not src.exists():
            raise click.ClickException(f"Template file missing: {literal}")
        if literal == "gitignore":
            dst = output_path / ".gitignore"
        elif literal == "CODEOWNERS":
            dst = output_path / ".github" / "CODEOWNERS"
        else:
            dst = output_path / literal
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text())
        written.append(str(dst.relative_to(output_path)))

    # 3. Create empty directories with .gitkeep
    for empty_dir in EMPTY_DIRS:
        gitkeep = output_path / empty_dir / ".gitkeep"
        gitkeep.parent.mkdir(parents=True, exist_ok=True)
        gitkeep.touch()
        written.append(f"{empty_dir}/.gitkeep")

    # 4. Validate required outputs
    missing = [f for f in REQUIRED_OUTPUT_FILES if not (output_path / f).exists()]
    if missing:
        raise click.ClickException(f"Scaffold validation failed: missing {missing}")

    # 5. Report + next-steps
    click.echo("")
    click.echo(f"✓ Scaffolded {repo_name} at {output_path}")
    click.echo(f"  ({len(written)} files)")
    click.echo("")
    click.echo("Next steps:")
    click.echo(f"  cd {output_path}")
    click.echo("  npm install")
    click.echo('  git init && git add -A && git commit -m "init: scaffold per handbook mcp-server.md"')
    click.echo(f"  gh repo create juvantlabs/{repo_name} --public \\")
    click.echo(f'    --description "{description}"')
    click.echo("  git remote add origin git@github.com:juvantlabs/{repo_name}.git".format(repo_name=repo_name))
    click.echo("  git branch -M main && git push -u origin main")
    click.echo("")
    click.echo("Then implement your tools in src/tools/, wire auth in src/auth/,")
    click.echo("and follow the handbook spec at:")
    click.echo("  https://github.com/juvantlabs/handbook/blob/main/docs/repo-types/mcp-server.md")


if __name__ == "__main__":
    sys.exit(scaffold_mcp_server())
