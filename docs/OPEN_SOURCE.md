# Open-source and public-results checklist

Code and trading history are different kinds of information. The code can be
public while your raw broker records, credentials, account identifiers, tax
lots, and exact portfolio value remain private.

## Before making the repository public

- Confirm every contributor has the right to license their work under
  Apache-2.0. Employer-owned code and copied snippets need explicit clearance.
- Generate a dependency-license report and preserve every package's own terms.
  The current lock includes LGPLv3 `frozendict` through `yfinance`; it is not
  relicensed by Edgecraft, and bundled distributions need a separate license
  compliance review.
- Run `make validate`, `make security`, and a full-history secret scan from a
  clean clone.
- Inspect the complete Git history, not only the current working tree. Deleting
  a secret in a later commit does not remove it from earlier commits.
- Review Git author names and emails for information you do not want public.
- Confirm `.env`, `state/`, `artifacts/`, `data/cache/`, databases, logs, and
  broker exports are ignored and absent from every Git revision.
- Enable GitHub secret scanning, push protection, private vulnerability
  reporting, Dependabot alerts, branch protection, and required CI checks.
- Use a clean release clone. Do not publish directly from a working directory
  that also holds live broker state.

If a real credential has ever been committed, revoke or rotate it first. A
history rewrite is cleanup, not credential rotation.

## Sharing trades and performance

Publish a deliberately small, generated dataset rather than the SQLite ledger
or a raw Robinhood response. A public trade record should contain only what the
story needs, for example:

```json
{
  "executed_at": "2026-07-20T17:00:00Z",
  "symbol": "VTI",
  "side": "buy",
  "notional_usd": 10,
  "status": "filled",
  "strategy": "plain_dca"
}
```

Leave out account and broker order identifiers, permit tokens, exact buying
power, tax lots, device information, raw prompts, and free-text broker errors.
Consider whether publishing exact timestamps or exact portfolio values reveals
more than you intend. Monthly aggregation or normalized returns may be safer.

Performance reports should state:

- the start and end dates, deposits, fees, and benchmark;
- whether returns are time-weighted or money-weighted;
- whether results are backtest, shadow, or live;
- missing data and methodology changes;
- that past performance does not guarantee future results.

Keep the private source dataset outside the repository. Generate the public
artifact one way, validate it against a strict schema, scan it for identifiers,
and review the final diff before publishing.

## Current readiness record

On July 20, 2026, the tracked tree and reachable Git history were scanned for
common credential formats, private-key material, and non-placeholder account or
broker order identifiers; none were found. Dependency vulnerability scanning
reported no known vulnerabilities in the locked runtime set. Static analysis
reported no high-severity findings. These are point-in-time checks and must be
rerun immediately before the repository changes visibility.
