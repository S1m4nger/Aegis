# Custom Rule Engine — DSL and semantics

## Safety
- Declarative JSON AST only. Never use `eval`, expression language interpreter accepting arbitrary code, templating, reflection over untrusted fields, SQL strings or arbitrary file reads.
- Validate entire rule set **at startup**: allowed fields, types, operators, node depth <= 8, total leaf count <= 64 per rule, number of rules <= 200, `risk_weight` in [0,1]. Invalid config must fail startup with explicit redacted error.
- Only `type`, `amount`, `step` (or future preapproved derived fields) can be inspected. Never `isFraud`, `isFlaggedFraud`, post-balance columns, IDs.
- Deterministic evaluation, stable ordering by priority then rule id. Rule's explanation says WHICH PREDICATE fired, not alleged identity/location/behaviour unavailable from dataset.

## JSON format
```json
{
  "version": "1.0",
  "rules": [
    {
      "id": "large_transfer",
      "priority": 10,
      "enabled": true,
      "risk_weight": 0.55,
      "when": {
        "op": "and",
        "children": [
          {"op": "eq", "field": "type", "value": "TRANSFER"},
          {"op": "gte", "field": "amount", "value": 100000.0}
        ]
      },
      "explanation": "Transfer amount is above a training-selected threshold"
    }
  ]
}
```

Threshold 100000 above is a placeholder; never claim it optimal. Codex must fit/justify thresholds on Train/Selection. If rule does not fire, output must not contain false matches.

## Operators
Comparators `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, with strict type validation; boolean `and`, `or` as nested child AST nodes. Add `not` only if tested. Empty AND / OR invalid. Type-specific: numeric comparisons only on amount/step; string eq/in only on `type`. Missing fields must return error, not false silently.

## Score / explanation
- Each fired rule contributes a **heuristic** weight; simple aggregation: `score = 1 - product(1 - weight_i)`. Value bounded [0,1] but NOT automatically probability. Every fired rule is listed with weight, priority and reason.
- Ability to run rules-only with documented threshold. Calibration/threshold selection may be compared but no relabeling test data.
- Conflict type from independent ML score and heuristic rule score cutoffs fixed on Selection: `ML_ONLY_HIGH`, `RULES_ONLY_HIGH`, `BOTH_HIGH`, `BOTH_LOW`; disagreement group is observable without labels.

## DSL edge cases
Unknown op/field; type mismatch; negative/NaN/infinity; deeply nested AST; malformed JSON; missing value; empty children; zero weight; disabled rules; stable priority ordering; duplicated IDs. Test each temporarily and remove executable files after run; preserve verification outcome.

## Verified implementation
Startup rejects null/negative/nonfinite numeric constants, out-of-range or fractional step constants, duplicate IDs, unknown fields/operators, malformed logical nodes, depth over 8 and more than 64 total AST nodes per rule (a deliberately stricter bound than 64 leaves). Nested AND/OR, type membership, disabled rules and priority/ID ordering were exercised with generated temporary Go tests; source removed after execution. Scores use the documented product aggregation and remain heuristic.
