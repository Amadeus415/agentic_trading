# Edgecraft

Build an understandable autonomous paper hedge fund powered by a Codex subscription. Aim for aggressive compounded growth and measurable outperformance against the S&P 500.

- Search eagerly, manage short-term positions, and learn from outcomes. Trade only when the expected edge clears costs; never force fills.
- Codex researches and proposes. Python owns quotes, sizing, exits, accounting, and limits. Every fill is simulated; no broker, wallet, transfer, or real-order tools.
- Preserve the one-time bankroll and append-only ledger. Never erase losses, rewrite history, or weaken gates to pass a decision.
- Trading runs follow `docs/CODEX_SCHEDULED_TASK.md`: one packet, one apply, verify, stop on failure. Research runs do not edit tracked source or policy.
- Reviews follow `docs/EVOLUTION.md` every seven days or 20 additional closed trades. Test new versions separately; do not borrow a parent's track record.
- Keep one operational path, one ledger, and a read-only dashboard. Prefer deleting unnecessary complexity to adding frameworks.
- Keep private state and credentials out of Git. Preserve unrelated work. Run `make validate`; dashboard changes also require lint, tests, build, and DB smoke.
- Explain claims honestly: simulated performance, sample size, benchmark window, and unproven assumptions. Split commits by idea and explain why each change matters.
