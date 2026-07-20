# Contributing

Thanks for taking a look at Edgecraft. Small, focused changes are easiest to
review.

## Before opening a pull request

1. Create an issue or short proposal for changes to the trading authority,
   broker boundary, data model, or public API.
2. Use synthetic, placeholder, or properly licensed public market data. Never
   commit real account IDs, order IDs, broker payloads, credentials, tax data,
   or another person’s trading history.
3. Keep all new mandates and examples in shadow mode. Tests must not place or
   cancel a real order.
4. Add tests for the success path and the important failure paths.
5. Run the checks:

   ```bash
   make validate
   make security
   ```

By submitting a contribution, you agree that it is licensed under Apache-2.0,
the same license as the project, and that you have the right to submit it.

For vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening an
issue or pull request.
