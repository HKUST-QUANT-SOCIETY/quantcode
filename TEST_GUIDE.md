# QuantCode v5 Testing Guide

## Commands

```bash
PYTHONPATH=. pytest -q
PYTHONPATH=. pytest -q tests/spec_v5
```

Real external-service tests must opt in explicitly and report the environment. Local tests may use deterministic fixtures, but fixtures must never be asserted as production evidence.

## Required test metadata

```yaml
spec_version: v0.5
commit:
date:
environment:
external_services:
real_or_mock:
test_scope:
passed:
failed:
blocked:
known_legacy_tests:
```

## v5 boundaries

- Session Group comes from server context; request/Resume cannot override it.
- Ordinary HumanGate kinds are only `merge` and `permission`.
- Risk/Portfolio verdicts do not interrupt.
- Budget and loop detection return `stopped_budget` / `stopped_loop`.
- Ordinary Tool Catalogs do not contain deployment.
- QuantEvaluator disconnection returns `UNAVAILABLE`, not mock IC/IR.
- Capability maturity and integration status are separate.
- Runtime State is not listed as Group Memory.
- GitGraph/Pop must expose source, visibility, baseline, observed time and honest partial/error states.

Tests that protect pre-v5 behavior belong only under `docs/archive/pre-v5` as historical material; they must not remain executable.
