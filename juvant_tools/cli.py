"""juvant-tools CLI root.

Run via:
    python -m juvant_tools.cli <command> [args]
or, after `pip install -e .`:
    juvant-tools <command> [args]
"""

from __future__ import annotations

import click

from juvant_tools.scaffolders.mcp_server.scaffold import scaffold_mcp_server


@click.group()
@click.version_option(message="juvant-tools %(version)s")
def cli() -> None:
    """juvant-tools — utility scripts for the Juvant OS ecosystem.

    Generic dev tools that adopters of the Juvant OS framework can use
    across their per-company instances. Per the handbook
    docs/repo-types/toolbox.md spec.
    """


@cli.group()
def scaffold() -> None:
    """Scaffold new repos following the handbook docs/repo-types/ spec."""


scaffold.add_command(scaffold_mcp_server, name="mcp-server")


if __name__ == "__main__":
    cli()
