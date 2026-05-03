"""Tests for the mcp-server scaffolder.

Smoke-test the scaffold produces all required files + the validation
guard rejects bad input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from juvant_tools.scaffolders.mcp_server.scaffold import (
    REQUIRED_OUTPUT_FILES,
    scaffold_mcp_server,
)


def test_scaffold_creates_all_required_files(tmp_path: Path) -> None:
    """Scaffolding produces every file in REQUIRED_OUTPUT_FILES."""
    runner = CliRunner()
    output = tmp_path / "test-vendor-mcp-server"

    result = runner.invoke(
        scaffold_mcp_server,
        [
            "--vendor",
            "test-vendor",
            "--scope",
            "read",
            "--description",
            "Test vendor MCP server (smoke test).",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output

    for required in REQUIRED_OUTPUT_FILES:
        path = output / required
        assert path.exists(), f"Required file missing: {required}"
        assert path.stat().st_size > 0, f"Required file empty: {required}"


def test_scaffold_writes_juvant_srls_in_license(tmp_path: Path) -> None:
    """LICENSE must list Juvant Srls as copyright holder, not juvantlabs."""
    runner = CliRunner()
    output = tmp_path / "test-vendor-mcp-server"

    result = runner.invoke(
        scaffold_mcp_server,
        [
            "--vendor",
            "test-vendor",
            "--description",
            "Test.",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output

    license_text = (output / "LICENSE").read_text()
    assert "Juvant Srls" in license_text, "Copyright holder must be Juvant Srls"
    assert "juvantlabs" not in license_text, (
        "LICENSE must not list 'juvantlabs' as copyright holder "
        "(see feedback_license_copyright_holder memory)"
    )


def test_scaffold_package_json_is_valid(tmp_path: Path) -> None:
    """Generated package.json parses cleanly + has required deps."""
    runner = CliRunner()
    output = tmp_path / "vendor-mcp-server"

    result = runner.invoke(
        scaffold_mcp_server,
        [
            "--vendor",
            "vendor",
            "--description",
            "Test.",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output

    package_json = json.loads((output / "package.json").read_text())
    assert package_json["name"] == "@juvantlabs/vendor-mcp-server"
    assert package_json["author"] == "Juvant Srls"
    assert package_json["license"] == "MIT"
    assert "@modelcontextprotocol/sdk" in package_json["dependencies"]
    # Per handbook mcp-server.md spec: SDK >= 1.25.2 required.
    sdk_version = package_json["dependencies"]["@modelcontextprotocol/sdk"]
    assert sdk_version.startswith("^1.25") or sdk_version.startswith("^1.26"), (
        f"MCP SDK must be >= 1.25.2 per spec; got {sdk_version}"
    )


def test_scaffold_rejects_invalid_vendor_name(tmp_path: Path) -> None:
    """Vendor with uppercase or invalid chars is rejected."""
    runner = CliRunner()

    result = runner.invoke(
        scaffold_mcp_server,
        [
            "--vendor",
            "BadVendor",  # uppercase
            "--description",
            "Test.",
            "--output",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code != 0
    assert "lowercase" in result.output.lower() or "alphanumeric" in result.output.lower()


def test_scaffold_refuses_existing_dir(tmp_path: Path) -> None:
    """Scaffold refuses to overwrite an existing output dir."""
    output = tmp_path / "existing"
    output.mkdir()

    runner = CliRunner()
    result = runner.invoke(
        scaffold_mcp_server,
        [
            "--vendor",
            "test",
            "--description",
            "Test.",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_scaffold_creates_empty_dirs_with_gitkeep(tmp_path: Path) -> None:
    """Empty directories (src/auth, tests/unit, etc.) have .gitkeep."""
    runner = CliRunner()
    output = tmp_path / "vendor-mcp-server"

    result = runner.invoke(
        scaffold_mcp_server,
        [
            "--vendor",
            "vendor",
            "--description",
            "Test.",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0

    for dir_name in ["src/auth", "src/tools", "src/client", "src/types", "tests/unit", "tests/integration"]:
        gitkeep = output / dir_name / ".gitkeep"
        assert gitkeep.exists(), f".gitkeep missing in {dir_name}"


def test_scaffold_renders_vendor_titled_in_readme(tmp_path: Path) -> None:
    """README uses vendor_titled (CamelCase from hyphenated vendor)."""
    runner = CliRunner()
    output = tmp_path / "aruba-fattura-mcp-server"

    result = runner.invoke(
        scaffold_mcp_server,
        [
            "--vendor",
            "aruba-fattura",
            "--description",
            "Italian SDI e-invoicing.",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0

    readme = (output / "README.md").read_text()
    assert "Aruba Fattura MCP Server" in readme
    assert "aruba-fattura" in readme  # the lowercase form too


def test_scaffold_no_console_log_in_index_ts(tmp_path: Path) -> None:
    """Generated src/index.ts must use console.error only, never console.log
    (CSO Layer 5 stdout-discipline rule from handbook mcp-server.md)."""
    runner = CliRunner()
    output = tmp_path / "vendor-mcp-server"

    result = runner.invoke(
        scaffold_mcp_server,
        [
            "--vendor",
            "vendor",
            "--description",
            "Test.",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0

    index_ts = (output / "src" / "index.ts").read_text()
    assert "console.log" not in index_ts, (
        "src/index.ts must not use console.log (corrupts MCP stdio framing)"
    )
    assert "console.error" in index_ts  # acceptable
