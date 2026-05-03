"""MCP stdio server for juvant-tools.

Exposes a curated subset of juvant-tools functionality as MCP tools so
agents (Claude Code, Juvant OS instances, any MCP-aware client) can
invoke them directly. Today: `scaffold_mcp_server`. The list is
deliberately minimal — tools are added pull-driven, when an agent has
a real need, not push-driven.

Run via:

    juvant-tools-mcp                    # (after pip install '.[mcp]')
    python -m juvant_tools.mcp_server   # equivalent

Bind from a Juvant OS instance via `.juvant/config.json`:

    {
      "tools": {
        "provider": "juvant-tools",
        "mcp_server": "juvant-tools-mcp",
        "scope": "rw"
      }
    }

Errors

Tool calls always return a dict with a top-level `status` key
(`"ok"` or `"error"`). On error, `error` is a stable string code an
agent can branch on (e.g. `"output_path_exists"`,
`"invalid_vendor_name"`, `"validation_failed"`). See each tool's
docstring for the codes it can produce.

The MCP SDK is an optional dep (`pip install 'juvant-tools[mcp]'`).
This module imports cleanly without it (the `main()` entry point
errors out with an install hint), so testing the pure handlers
doesn't require the SDK.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from juvant_tools.scaffolders.mcp_server.scaffold import (
    InvalidScopeError,
    InvalidVendorNameError,
    OutputPathExistsError,
    ScaffoldError,
    scaffold_mcp_server_repo,
)


# =====================================================================
# Tool handler — pure dict-returning function, MCP-SDK-free for testability
# =====================================================================

def _scaffold_mcp_server_handler(
    vendor: str,
    description: str,
    output_path: str,
    scope: str = "read",
) -> dict[str, Any]:
    """Pure handler: scaffold an MCP server repo and return a structured
    result dict.

    Always returns a dict (never raises). Decoupled from the MCP SDK
    so tests can call it directly without `mcp` installed.

    Returns on success:
        {
          "status": "ok",
          "output_path": str,
          "repo_name": str,
          "files_written": list[str]
        }

    Returns on error (status="error"), with `error` set to one of:
        - "invalid_vendor_name": vendor didn't match the regex
        - "invalid_scope": scope wasn't "read" or "rw"
        - "output_path_exists": destination already exists
        - "template_missing": scaffolder install is corrupted
        - "validation_failed": post-render check found a required file missing
    """
    try:
        result = scaffold_mcp_server_repo(
            vendor=vendor,
            scope=scope,
            description=description,
            output_dir=Path(output_path),
        )
    except OutputPathExistsError as e:
        return {
            "status": "error",
            "error": e.code,
            "output_path": str(e.output_path),
            "hint": "Choose a different output_path, or remove the existing directory first.",
        }
    except InvalidVendorNameError as e:
        return {
            "status": "error",
            "error": e.code,
            "vendor": vendor,
            "hint": "vendor must be lowercase, alphanumeric + hyphens, starting with a letter.",
            "message": str(e),
        }
    except InvalidScopeError as e:
        return {
            "status": "error",
            "error": e.code,
            "scope": scope,
            "hint": 'scope must be "read" or "rw".',
            "message": str(e),
        }
    except ScaffoldError as e:
        return {
            "status": "error",
            "error": e.code,
            "message": str(e),
        }

    return {
        "status": "ok",
        "output_path": str(result.output_path),
        "repo_name": result.repo_name,
        "files_written": result.files_written,
    }


# =====================================================================
# FastMCP wiring (optional — gated on `mcp` SDK being installed)
# =====================================================================

try:
    from mcp.server.fastmcp import FastMCP  # noqa: PLC0415
except ImportError:
    FastMCP = None  # type: ignore[assignment,misc]


if FastMCP is not None:
    _server = FastMCP("juvant-tools")

    @_server.tool()
    def scaffold_mcp_server(
        vendor: str,
        description: str,
        output_path: str,
        scope: str = "read",
    ) -> dict[str, Any]:
        """Scaffold a new juvantlabs/<vendor>-mcp-server repo skeleton.

        Generates a directory at `output_path` containing all 15 files
        required by the handbook docs/repo-types/mcp-server.md spec,
        ready to commit. Refuses to overwrite an existing directory —
        on `output_path_exists`, choose a different path or remove the
        existing directory first.

        Args:
            vendor: Lowercase, hyphenated identifier (e.g. "finom",
                "aruba-fattura"). Must match `^[a-z][a-z0-9-]*$`.
            description: One-line description of what the vendor's API
                exposes. Goes into README + package.json.
            output_path: Absolute or repo-relative path where the new
                directory should be created. Refuses to overwrite.
            scope: MCP scope qualifier — `"read"` (default) or `"rw"`.

        Returns:
            Dict with `status` ("ok" or "error"). On ok: output_path,
            repo_name, files_written. On error: error code (one of
            "invalid_vendor_name", "invalid_scope", "output_path_exists",
            "template_missing", "validation_failed") plus optional
            error-specific keys.
        """
        return _scaffold_mcp_server_handler(
            vendor=vendor,
            description=description,
            output_path=output_path,
            scope=scope,
        )


# =====================================================================
# Entry point
# =====================================================================

def main() -> None:
    """Run the MCP server over stdio. Requires `mcp` SDK installed."""
    if FastMCP is None:
        print(
            "ERROR: MCP SDK not installed.\n"
            "Install with: pip install 'juvant-tools[mcp]'",
            file=sys.stderr,
        )
        sys.exit(1)
    _server.run()


if __name__ == "__main__":
    main()
