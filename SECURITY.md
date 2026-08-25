# Security policy

## Active product boundary

The Edgecraft paper fund is fake-money-only by construction:

- `FundMandate` has no live mode.
- `paper_fund.py` imports no broker client or execution adapter.
- The scheduled script invokes only `fund-init`, `fund-verify`, and `fund-run`.
- The repository contains no broker mutation path, permit, or live policy.
- Generated ledgers and decision inputs are gitignored.
- SQLite cycles and events are append-only and hash-chained.

Do not add a broker call, live mandate, credential, or mutating financial tool to the fund domain or scheduled prompt.

## Sensitive data

Never commit or retain:

- credentials, OAuth tokens, cookies, or API keys;
- account numbers, broker exports, tax records, or private balances;
- unnecessary personal information;
- raw private messages or form contents;
- generated SQLite ledgers or state packets.

Public evidence packets should contain concise claims and direct source URLs, not copied articles or secrets.

## Dependency and source checks

Run `make validate` and `make security` before release. CI runs tests and static checks; the repository also uses dependency updates and secret scanning.

## Reporting

Report suspected vulnerabilities privately through GitHub's security advisory flow. Include affected version, reproduction, impact, and a proposed mitigation if available. Do not open a public issue for an unpatched secret or execution-boundary problem.
