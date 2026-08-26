# Real Backtest Executor Evidence

`rb_dual_ma_real_backtest_v1.json` is a Server B executor-validation artifact, not a claim about the strategy in any QuantCode pull request.

The discovery subagent selected an available 500,000-row RB one-minute market benchmark and the trusted `quantsociety_backend` Backtrader engine. The deterministic executor ran a 20/100 dual moving-average strategy with 1 bp commission and 1 bp slippage, strict timestamp validation, no shorting, and next-bar execution semantics. Raw market data and the 21 MB equity curve remain on Server B; this repository tracks only aggregate metrics and content hashes.

Two independent isolated runs were byte-identical:

- aggregate artifact SHA-256: `686f6627437fb17880ae941e977d29ef2e019839ea9489529c107426ee94fed6`
- normalized OHLCV SHA-256: `60c3961a0f7c9fb4befd4cd4d32415ef93adc25da6fb4dd1f06e140e14fa29db`
- equity curve SHA-256: `812878d53ea48c20067baff0940def066f170be03312a0d11ddb2a2da85f0108`

The executor worked, but the strategy result is a clear risk failure: total return `-74.06%`, annual return `-62.45%`, Sharpe `-6.91`, maximum drawdown `74.64%`, and 6,689 trades. A full Risk Gate artifact also remains `not_evaluable` because no existing-portfolio return series or ADV/impact inputs were available for correlation and capacity. Missing evidence is never replaced with zero or a fabricated estimate.

This evidence establishes the real-data execution path. PR-level approval still requires a planner-generated, head-bound `RiskGatePlan` that identifies the actual changed strategy and immutable data snapshot.
