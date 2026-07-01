# Sample Model PR for Risk Gate

This document is a lightweight model-group sample used by the T2 risk team to test risk-gate behavior.

## Model Summary

- Model name: sample-mean-reversion
- Group: model
- Asset universe: US equities
- Signal type: mean reversion
- Rebalance frequency: daily

## Expected Risk Inputs

- max_drawdown should be checked
- position_limit should be checked
- correlation with existing strategies should be checked
- VaR should be checked

## Notes

This PR is intentionally small. It exists as a realistic model-group PR fixture for risk-gate testing.