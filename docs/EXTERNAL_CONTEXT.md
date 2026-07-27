# External web and social context

Edgecraft gathers a small, auditable context packet before the model forms a
weekly decision. The packet complements—not replaces—broker truth, price
history, causal backtests, and deterministic risk controls.

Each source is labeled with `source_quality` (`primary`, `secondary`, or
`unverified`) and `evidence_role` (`fact`, `management_claim`, `analysis`, or
`sentiment`). Reputation alone never upgrades a source. Podcasts, investor
posts, and general social activity may generate research questions or reduce
confidence; they cannot independently support an allocation.

## Why Browserbase

[Browserbase Search](https://docs.browserbase.com/platform/search/overview) is
the primary discovery provider. It returns structured URLs and publication
metadata without spending browser minutes. Edgecraft then uses
[Browserbase Fetch](https://docs.browserbase.com/platform/fetch/overview) for a
small number of diverse pages. The current
[free plan](https://www.browserbase.com/pricing) lists 1,000 Search calls, 1,000
Fetch calls, and one browser hour per month. Edgecraft does not need a full
browser session for its normal weekly path.

Small universes normally cost three Search calls: current news, SEC discovery,
and public social-page discovery. Larger universes are split into
symbol batches so every approved name can enter discovery without overflowing a
provider query; `max_search_queries` is the hard budget. Social search rotates
through individual symbols each day and never makes or retains more than
`social_results` direct-AppView requests/results in total. Set it to zero when
the public AppView is unavailable; Browserbase social-page discovery continues
independently.
Results are cached for 30 minutes so safe retries do not repeat paid or
rate-limited work.

## Source choices

| Source | Status | What it adds | Credential |
| --- | --- | --- | --- |
| Browserbase Search + Fetch | Integrated, required by supplied mandates | Current reporting, primary-source discovery, page excerpts | Free project API key |
| [SEC EDGAR submissions](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | Integrated when `sec_ciks` are configured | Official 8-K, 10-Q, 10-K, 6-K, 20-F, 40-F, and N-CSR filings | None |
| [Bluesky public AppView](https://docs.bsky.app/docs/advanced-guides/api-directory) | Integrated through the cached public AppView host | Public discussion and sentiment as a weak, untrusted signal | None |
| [FRED](https://fred.stlouisfed.org/docs/api/fred/overview.html) | Evaluated, not required | Macro series and vintage-aware economic context | User-issued API key |
| X and Reddit APIs | Not required | Additional social volume | Platform auth/cost and materially more abuse/noise handling |

FRED is a strong future macro-regime input, but adding its separate key would
not improve company/ETF news discovery enough to justify making it part of the
first required path. X and Reddit can be added behind the same typed provider
boundary later; they should not become live-trading dependencies without source
quality, manipulation, and outage tests.

## Configure Browserbase

Create a free Browserbase project and copy its API key. For an interactive
shell, keep the key outside the repository:

```bash
export BROWSERBASE_API_KEY='your-key'
uv run edgecraft context \
  --config examples/context.browserbase.json \
  --symbols VTI,VXUS,BND \
  --output artifacts/current-context.json
```

For unattended operation, put only the key in a private file outside the
repository, set its permissions to `0600`, and export its path in the local
scheduled-task environment:

```bash
export BROWSERBASE_API_KEY_FILE="$HOME/.config/edgecraft/browserbase_api_key"
```

The scheduled task receives only the file path; it should not copy
`BROWSERBASE_API_KEY`. `edgecraft health` reports whether either credential
form is available but never prints the key.

## Safety and decision contract

The collection path:

```text
batch symbols
  → Browserbase current-news + SEC-domain searches
  → fetch a few domain-diverse pages
  → public Bluesky search + configured SEC submissions
  → strip active HTML, cap excerpts, deduplicate, freshness-check
  → private 30-minute cache + append-only run audit event
  → model receives explicitly untrusted evidence
  → invest decision must cite known source IDs
  → deterministic portfolio/risk gate
```

Important boundaries:

- Only public HTTPS URLs are accepted; literal local, private, and reserved
  addresses are rejected.
- Page scripts, styles, SVG, and markup are removed. Excerpts are length-capped.
- The model is told never to follow instructions from retrieved content. Social
  posts are sentiment, not facts.
- Social collection is optional by default. A manipulable, unvalidated channel
  must not become a live-trading availability dependency.
- A live mandate must name an external-context policy. If collection does not
  meet configured source, web-source, freshness, and channel minimums, the run
  stops before a proposal or execution permit exists.
- Invest decisions must cite at least the configured number of source IDs and
  cannot cite an ID outside the collected packet. Holding cash remains valid.
- Search context never weakens budget, symbol, cash, concentration, quote
  freshness, open-order, market, review, permit, or kill-switch controls.

Tune `examples/context.browserbase.json` conservatively. `sec_ciks` must be an
explicit symbol-to-CIK mapping and requires a compliant `sec_user_agent` with
the operator's contact email. Edgecraft does not guess issuer identity from an
ambiguous ticker.
