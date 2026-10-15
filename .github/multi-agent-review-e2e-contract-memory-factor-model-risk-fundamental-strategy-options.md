# QuantCode Multi-Agent Review E2E Probe

Probe ID: `server-b-deepseek-e2e-2026-08-25`

This documentation-only change validates the trusted `pull_request_target` review path after its workflow has landed on `main`.

Expected evidence:

- Server B accepts the same-repository PR through the selected runner group.
- Deterministic physical gates consume the exact base and head SHAs.
- The combined result contains all six configured reviewer names.
- DeepSeek receives only the PR diff and review context through the approved endpoint.
- The bot updates one advisory PR comment and publishes a head-bound `Quant Review Gate` status.

The filename intentionally routes this harmless Markdown diff through every QuantCode reviewer category. It changes no runtime, credential, risk threshold, research result, or production path.
