# Contributing to `juvantlabs/juvant-tools`

This repo is a **toolbox** per the
[`docs/repo-types/toolbox.md`](https://github.com/juvantlabs/handbook/blob/main/docs/repo-types/toolbox.md)
spec at `juvantlabs/handbook`. The meta contributor guide (where to
file what, PR process, commit style, CoC, AI-assisted contribution
conventions) lives at
[handbook CONTRIBUTING.md](https://github.com/juvantlabs/handbook/blob/main/CONTRIBUTING.md).

## Quick path to land a new tool

1. **Open an issue** describing the tool you'd like to add. Confirm
   fit: is this the right repo (vs. library / MCP server / framework)?
   Is the tool **OSS-shareable** (no business-confidential coupling)?
2. **Implement** the tool. Place under `<tool-category>/<tool-name>`
   (categories will emerge as the toolbox grows; see README for
   planned categories).
3. **Document** in the matching subdirectory's README + add a row to
   the top-level README's tool list. Header comment in the tool
   source explaining what it does and prerequisites (e.g. "requires
   `gh` CLI authenticated").
4. **Smoke test** — at minimum, the tool runs with `--help` and
   returns exit 0. Heavier tests are welcome; light tests are
   acceptable for ad-hoc utilities.
5. **PR** with `<area>: <tool name + brief>` subject. Body explains
   why the tool is needed.

## Light vs. heavier formality

Per the toolbox spec, this repo accepts **lighter formality** than
libraries / MCP servers — the bar is "discoverable and runnable", not
"library-grade documentation". Quick-and-dirty scripts are welcome
when the value is real and the maintenance cost is low.

When a tool earns it (≥ 3 distinct users, weekly use,
production-critical), it can be promoted to a packaged
distribution (PyPI / npm) — see toolbox.md "Promote to registry"
lifecycle step.

## Anti-patterns

Do NOT add to this repo:

- Tools with hardcoded business identifiers (counterparty names,
  internal URLs).
- Tools that only work against a single private product (those go to
  `juvantio/<product>-dev-tools`).
- Hardcoded credentials of any kind.

If a tool drifts from generic to product-specific over time, split it:
extract the generic core back here, leave the product-specific
extension at `juvantio/<product>-dev-tools`.

## Code of conduct

All interactions in this repo follow the
[handbook Code of Conduct](https://github.com/juvantlabs/handbook/blob/main/docs/contributing/code-of-conduct.md).
Enforcement: `conduct@juvant.io`.

## AI-assisted contributions

AI-assisted commits include the standard co-author tag:

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Human author of the PR remains accountable for the change.
