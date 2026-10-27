# Contributing

Small, focused changes are easiest to review.

1. Open an issue first for anything that changes what agents face or how they are scored. Those changes need a new benchmark version (see `AGENTS.md`).
2. Keep the runtime dependency-free and paper-only. No broker, wallet or order endpoints.
3. Add tests for the behavior you change. Tests use fake venues and never call the network or a model.
4. Run `make check`.

By submitting a contribution, you agree that it is licensed under Apache-2.0.
