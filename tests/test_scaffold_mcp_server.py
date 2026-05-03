"""Tests for the mcp-server scaffolder.

Covers three surfaces:
- The pure function `scaffold_mcp_server_repo` (raises typed errors).
- The CLI subcommand `juvant-tools scaffold mcp-server` (smoke + edge cases).
- The MCP tool handler `_scaffold_mcp_server_handler` (returns structured
  dicts; runs without the `mcp` SDK installed).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from juvant_tools.mcp_server import _scaffold_mcp_server_handler
from juvant_tools.scaffolders.mcp_server.scaffold import (
    REQUIRED_OUTPUT_FILES,
    InvalidScopeError,
    InvalidVendorNameError,
    OutputPathExistsError,
    ScaffoldResult,
    scaffold_mcp_server,
    scaffold_mcp_server_repo,
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


def _scaffold(tmp_path: Path, vendor: str = "vendor") -> Path:
    """Helper: scaffold an MCP server in tmp_path and return the output dir."""
    runner = CliRunner()
    output = tmp_path / f"{vendor}-mcp-server"
    result = runner.invoke(
        scaffold_mcp_server,
        ["--vendor", vendor, "--description", "Test.", "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    return output


def test_scaffold_includes_ci_workflow(tmp_path: Path) -> None:
    """v0.2: CI workflow must exist + cover all 8 spec checks."""
    output = _scaffold(tmp_path)
    ci_yml = (output / ".github" / "workflows" / "ci.yml").read_text()

    # All 8 CI requirements from handbook docs/repo-types/mcp-server.md
    assert "npm run lint" in ci_yml
    assert "npm run typecheck" in ci_yml
    assert "npm run test:unit" in ci_yml
    assert "npm run test:integration" in ci_yml
    assert "npm audit --audit-level=moderate" in ci_yml
    assert "console.log" in ci_yml  # stdout discipline grep
    assert "validate|sanitize|guard|enforce|assert" in ci_yml  # dead-code grep
    assert "## Environment variables" in ci_yml  # README env-var accuracy check


def test_scaffold_includes_publish_workflow(tmp_path: Path) -> None:
    """v0.2: Publish workflow must exist + gate on the 'production' environment."""
    output = _scaffold(tmp_path)
    publish_yml = (output / ".github" / "workflows" / "publish.yml").read_text()

    assert "tags: ['v*.*.*']" in publish_yml
    # Manual approval gate
    assert "environment:" in publish_yml
    assert "production" in publish_yml
    # Provenance + auth
    assert "id-token: write" in publish_yml
    assert "NPM_TOKEN" in publish_yml
    assert "npm publish" in publish_yml


def test_scaffold_includes_eslint_config(tmp_path: Path) -> None:
    """v0.2: ESLint flat config must block console.log but allow console.error."""
    output = _scaffold(tmp_path)
    eslint_config = (output / "eslint.config.mjs").read_text()

    # Stdout discipline rule
    assert "no-console" in eslint_config
    assert "allow: ['error', 'warn']" in eslint_config or "allow: [\"error\", \"warn\"]" in eslint_config
    # Strict TS rules
    assert "@typescript-eslint" in eslint_config
    assert "no-explicit-any" in eslint_config


def test_scaffold_includes_vitest_config(tmp_path: Path) -> None:
    """v0.2: vitest config must enforce ≥80% coverage thresholds (per spec)."""
    output = _scaffold(tmp_path)
    vitest_config = (output / "vitest.config.ts").read_text()

    assert "coverage" in vitest_config
    assert "v8" in vitest_config  # provider
    # Spec mandates ≥ 80%
    assert "lines: 80" in vitest_config
    assert "functions: 80" in vitest_config
    assert "branches: 80" in vitest_config


def test_scaffold_index_ts_reads_log_level_env(tmp_path: Path) -> None:
    """v0.2: src/index.ts must reference process.env.MCP_SERVER_LOG_LEVEL.

    The CI README env-var accuracy check fails the build if README documents
    an env var that's not wired into src/. The fresh scaffold must pass that
    check on day 1, so MCP_SERVER_LOG_LEVEL needs to be read somewhere in src/.
    """
    output = _scaffold(tmp_path)
    index_ts = (output / "src" / "index.ts").read_text()
    assert "process.env.MCP_SERVER_LOG_LEVEL" in index_ts


def test_scaffold_package_json_has_v02_scripts_and_deps(tmp_path: Path) -> None:
    """v0.2: package.json adds test:unit / test:integration scripts +
    @vitest/coverage-v8 dev dep (needed by the CI coverage step)."""
    output = _scaffold(tmp_path)
    package_json = json.loads((output / "package.json").read_text())

    scripts = package_json["scripts"]
    assert "test:unit" in scripts
    assert "test:integration" in scripts

    dev_deps = package_json["devDependencies"]
    assert "@vitest/coverage-v8" in dev_deps


# =====================================================================
# v0.3 — pure function (scaffold_mcp_server_repo)
# =====================================================================

def test_pure_function_returns_scaffold_result(tmp_path: Path) -> None:
    """The pure function returns a ScaffoldResult with output_path / repo_name /
    files_written populated, matching the CLI's behavior."""
    output = tmp_path / "test-mcp-server"
    result = scaffold_mcp_server_repo(
        vendor="test",
        scope="read",
        description="Test MCP server.",
        output_dir=output,
    )
    assert isinstance(result, ScaffoldResult)
    assert result.output_path == output
    assert result.repo_name == "test-mcp-server"
    assert len(result.files_written) >= len(REQUIRED_OUTPUT_FILES)
    for required in REQUIRED_OUTPUT_FILES:
        assert (output / required).exists()


def test_pure_function_raises_invalid_vendor_name(tmp_path: Path) -> None:
    with pytest.raises(InvalidVendorNameError) as exc_info:
        scaffold_mcp_server_repo(
            vendor="BadVendor",
            scope="read",
            description="x",
            output_dir=tmp_path / "out",
        )
    assert exc_info.value.code == "invalid_vendor_name"


def test_pure_function_raises_invalid_scope(tmp_path: Path) -> None:
    with pytest.raises(InvalidScopeError) as exc_info:
        scaffold_mcp_server_repo(
            vendor="vendor",
            scope="readwrite",  # invalid; valid are "read" or "rw"
            description="x",
            output_dir=tmp_path / "out",
        )
    assert exc_info.value.code == "invalid_scope"


def test_pure_function_raises_output_path_exists(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(OutputPathExistsError) as exc_info:
        scaffold_mcp_server_repo(
            vendor="vendor",
            scope="read",
            description="x",
            output_dir=output,
        )
    assert exc_info.value.code == "output_path_exists"
    assert exc_info.value.output_path == output


# =====================================================================
# v0.3 — MCP tool handler (_scaffold_mcp_server_handler)
# =====================================================================

def test_mcp_handler_returns_ok_dict_on_success(tmp_path: Path) -> None:
    """Handler returns a structured dict with status='ok' on success."""
    output = tmp_path / "vendor-mcp-server"
    response = _scaffold_mcp_server_handler(
        vendor="vendor",
        description="Test.",
        output_path=str(output),
        scope="read",
    )
    assert response["status"] == "ok"
    assert response["output_path"] == str(output)
    assert response["repo_name"] == "vendor-mcp-server"
    assert isinstance(response["files_written"], list)
    assert len(response["files_written"]) >= len(REQUIRED_OUTPUT_FILES)


def test_mcp_handler_returns_output_path_exists_error(tmp_path: Path) -> None:
    """Handler returns status='error' / error='output_path_exists' when target
    directory already exists. Critical for agent retry — agent reads the
    error code instead of pattern-matching error text."""
    output = tmp_path / "existing"
    output.mkdir()
    response = _scaffold_mcp_server_handler(
        vendor="vendor",
        description="Test.",
        output_path=str(output),
    )
    assert response["status"] == "error"
    assert response["error"] == "output_path_exists"
    assert response["output_path"] == str(output)
    assert "hint" in response


def test_mcp_handler_returns_invalid_vendor_name_error(tmp_path: Path) -> None:
    response = _scaffold_mcp_server_handler(
        vendor="BadVendor",
        description="Test.",
        output_path=str(tmp_path / "out"),
    )
    assert response["status"] == "error"
    assert response["error"] == "invalid_vendor_name"
    assert response["vendor"] == "BadVendor"


def test_mcp_handler_returns_invalid_scope_error(tmp_path: Path) -> None:
    response = _scaffold_mcp_server_handler(
        vendor="vendor",
        description="Test.",
        output_path=str(tmp_path / "out"),
        scope="readwrite",
    )
    assert response["status"] == "error"
    assert response["error"] == "invalid_scope"


def test_mcp_handler_does_not_raise_on_any_error(tmp_path: Path) -> None:
    """The handler must always return a dict, never raise. Agent contract:
    a tool call's response is always JSON, never a thrown error from the SDK."""
    # All error paths
    output_existing = tmp_path / "existing"
    output_existing.mkdir()

    cases = [
        # (vendor, description, output_path, scope) — all known-bad
        ("vendor", "x", str(output_existing), "read"),    # output_path_exists
        ("BadName", "x", str(tmp_path / "a"), "read"),    # invalid_vendor_name
        ("vendor", "x", str(tmp_path / "b"), "weird"),    # invalid_scope
    ]
    for vendor, desc, path, scope in cases:
        response = _scaffold_mcp_server_handler(
            vendor=vendor, description=desc, output_path=path, scope=scope
        )
        assert isinstance(response, dict)
        assert response["status"] == "error"


def test_mcp_handler_module_imports_without_mcp_sdk() -> None:
    """The juvant_tools.mcp_server module must import cleanly even when the
    `mcp` SDK is not installed. The pure handler is decoupled from FastMCP
    so testing it doesn't require the SDK."""
    import juvant_tools.mcp_server as m
    # Handler always present
    assert callable(m._scaffold_mcp_server_handler)
    # FastMCP wiring is gated; main() errors out only at runtime if SDK absent
    assert callable(m.main)
