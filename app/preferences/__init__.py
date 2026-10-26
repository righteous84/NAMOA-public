"""
NAMOA preference domain (Phase 15, Phase A).

Example-driven user preference constraints for optimisation decisions.

This package holds ONLY the in-memory preference domain and the
deterministic example-to-rule compiler:

- dimensions.py  the single versioned allowlist of match dimensions,
                 normalisation, and compiler constants
- examples.py    explicit user preference examples (immutable records)
- rules.py       ordered preference rules with provenance
- compiler.py    deterministic compilation of examples into rules

What this package is NOT (hard Phase A boundary):

- no coverage evaluation (Phase B)
- no suggestions or lifecycle (Phase C)
- no sampling or wizard state (Phase D)
- no review/accept UI contracts (Phase E)
- no future-scan hooks (Phase F)
- no persistence, migrations, API endpoints, or UI
- no changes to decision rules, fusion, policy, or organisation
  behaviour; nothing here is imported by production paths

Matching semantics mirror the organisation unified-rule model
(conjunction of conditions, first match wins) without depending on
it: preference rules constrain optimisation input classes, they never
rearrange libraries.
"""
