# Security

## Reporting a vulnerability

Please report vulnerabilities **privately** via one of these channels:

1. **GitHub Security Advisory** (preferred) — go to this repo's
   `Security` tab → `Report a vulnerability`. Your report stays
   private between you and the maintainer until we publish a
   coordinated advisory.
2. **Email** — `security@juvant.io`. Reports go to the primary
   maintainer (today: Antonio Gatti).

**Please do NOT** open a public issue or pull request that contains
reproduction details for the vulnerability. Once a public artifact
exposes the issue, the coordinated-disclosure window collapses.

## What we commit to

This repo follows the
[juvantlabs Security Disclosure Process](https://github.com/juvantlabs/handbook/blob/main/docs/security/disclosure-process.md).
SLOs:

| State | Target |
|---|---|
| Acknowledge receipt | ≤ 7 days |
| Initial triage + severity classification | ≤ 14 days |
| Patch prepared (high/critical) | ≤ 30 days |
| Patch prepared (moderate) | ≤ 90 days |
| Public advisory + CVE | Patch + 1–7 days |

## Supported versions

This repo is currently **scaffold-only**; no production tools have
shipped. Once tools land and earn semver discipline, this section will
list supported versions.

## Out of scope

- Issues in dependencies — please report those upstream.
- Issues in adopter customizations of tools shipped here (after they
  ship).

## Crediting

Reporters are credited by name in advisories unless they request
anonymity at report time.

## Acknowledgments

No disclosures yet.
