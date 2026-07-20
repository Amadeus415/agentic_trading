# Security policy

Edgecraft can sit next to a real brokerage account, so security reports are
taken seriously.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. When this
repository becomes public, use GitHub’s private vulnerability-reporting form in
the repository’s **Security** tab. Until that is enabled, contact
[@Amadeus415](https://github.com/Amadeus415) with only a short description and a
request to arrange a private channel. Do not include credentials, account
numbers, live permit tokens, or another person’s data in the first message.

Include the affected version or commit, the impact, reproduction steps using
fake or shadow data, and any suggested mitigation. You should receive an
acknowledgement within seven days.

## Supported versions

Security fixes are applied to the latest commit on `main`. The project has not
made a stable release yet.

## Safety boundary

- New mandates and examples are shadow-only.
- Live execution requires an explicitly enabled live mandate, deterministic
  policy approval, Robinhood review, and an exact expiring single-use permit.
- The broker connection is provided by the host’s authenticated MCP session;
  credentials are not stored in this repository.
- Scoped agent subprocesses receive an allowlisted environment instead of
  inheriting arbitrary shell tokens or application secrets.
- The web app is a local operator surface bound to `127.0.0.1`. It has no
  internet-facing authentication or rate limiting and must not be exposed
  directly to a network.
- Local ledgers and runtime output may contain sensitive financial information.
  They belong in ignored local storage, never in an issue, fixture, or commit.

These controls reduce risk; they are not a warranty that the software is safe
for unattended trading or that a strategy will perform as expected.
