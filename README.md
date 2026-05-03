# juvant-tools

OSS-shareable utility scripts, dev tools, and CLI helpers for the Juvant OS
ecosystem. Toolbox repository per the
[`docs/repo-types/toolbox.md`](https://github.com/juvantlabs/handbook/blob/main/docs/repo-types/toolbox.md)
spec at `juvantlabs/handbook`.

## Status

**Scaffold-only.** First tool incoming via PR. The repo exists as the
canonical home for `juvantlabs/*` toolbox-class artifacts so future
contributions have a defined place to land — without having to set
up the convention each time.

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

## Planned tool categories (when populated)

The structure will emerge as real tools land. Likely categories:

| Category | Example tools | Status |
|---|---|---|
| Juvant OS instance hygiene | Lint a per-company instance against the framework's spec; audit `agent_tool_matrix` vs. `MCP_INVENTORY.md`; check for surviving placeholders | not yet |
| MCP server scaffolding | Generate a new `juvantlabs/<vendor>-mcp-server` skeleton from the [`mcp-server.md`](https://github.com/juvantlabs/handbook/blob/main/docs/repo-types/mcp-server.md) spec | not yet |
| Audit + disclosure helpers | Run a static-analysis audit on a community MCP server; produce a draft audit report per the [`audit-report-template.md`](https://github.com/juvantlabs/handbook/blob/main/docs/security/audit-report-template.md) | not yet |
| Local dev workflow | Helpers for testing hooks against a local Turso file, simulating webhook deliveries against `juvant-os` instances, etc. | not yet |

These are illustrative. Tools enter the toolbox when there's a real
need — no premature creation.

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
