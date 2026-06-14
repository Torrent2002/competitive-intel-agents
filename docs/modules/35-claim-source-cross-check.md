# 模块 35：Reviewer claim ↔ source 交叉校验

## Goal

Move beyond id-level structural checks (claim cites a source id, source
id exists, source is referenced by some claim) into content-level
verification: does the source text actually support the claim text?
Surface mismatches without forcing the report into rework.

## Scope

In scope:

- New `accuracy` field on `AnalysisClaim` with values
  `unverified` / `supported` / `partial` / `unsupported`; default
  `unverified` keeps analyst output untouched
- New `_verify_claim_support` method on `ReviewerAgent` that runs a
  single batched LLM call cross-checking every claim against its
  cited source content
- Failed verifications produce `unsupported_claim` advisories
  (`severity=advisory`, `blocking=False`)
- `partial` and `unsupported` verdicts persist a v2 of the claim with
  the new accuracy via `supersedes_id` lineage; `supported` and
  `unverified` leave the claim alone to avoid version-bump noise
- `Orchestrator` now promotes reviewer advisories to
  `RunResult.caveats` and switches the success path to
  `approved_with_caveats` when any advisory is present
- New helper `_approved_or_caveats_from_reviewer` shared by all
  reviewer-stop paths (direct, rework-loop)
- `claim_payload` exposes `accuracy` so writer prompts can flag claims
  in the rendered report
- 4 new unit tests in `tests/unit/test_reviewer_agent.py`,
  1 in `tests/unit/test_orchestrator.py`

Out of scope:

- Writer post-processing (the `accuracy` is in the prompt context;
  marker rendering relies on the LLM honoring the system prompt
  rather than deterministic post-edit)
- Per-claim model calls (single batched call only)
- Changes to `VALID_REVIEW_ISSUES` (existing `unsupported_claim`
  enum value is reused)
- New status enum (advisories flow through the existing
  `approved_with_caveats`)

## Design

### Verification flow

```
ReviewerAgent.run_round
  ↓
  rule_feedback = _review_report(...)              # existing 7 rule checks
  if model_runtime:
    model_feedback = _model_review(...)            # existing semantic review
    verification_feedback = _verify_claim_support(...)   # NEW
  ↓
  blocking = [fb for fb in all if fb.blocking]
  if blocking → decision=rework
  else → decision=stop, review_feedback=advisories
```

`_verify_claim_support`:

```
collect (claim, [source_excerpts]) pairs where content_ref exists
if none → return []
single LLM call: "judge each claim against its sources"
for each verdict:
  if accuracy in {partial, unsupported} and changed → save v2 with new accuracy
  if accuracy == unsupported → emit unsupported_claim advisory
return advisories
```

### Lineage

`_save_verified_claim` mints a new id `{claim.id}_v{n+1}_verified` to
keep the reviewer's bumps distinct from `ReworkLoop._replacement_id`'s
`{claim.id}_v{n}` pattern. This means a claim can simultaneously have
both a `_v2` (rework rewrite) and a `_v2_verified` (reviewer
cross-check verdict) without id collision.

`mark_superseded` is invoked through `getattr` so test stores without
the method don't break.

### Orchestrator advisory pickup

Three reviewer-stop entry points handle advisories the same way:

1. Top-level run loop (no rework path): direct `decision=stop` after
   reviewer round
2. `_apply_integrated_rework`: `rework_result.final_decision=stop`
3. `_apply_integrated_rework`: latest journal reviewer event has
   `decision=stop`

All three call `_approved_or_caveats_from_reviewer`:

```python
advisories = [fb for fb in latest_reviewer_event.review_feedback if not fb.blocking]
if advisories:
    return RunResult(status="approved_with_caveats", caveats=advisories, review_feedback=[])
return RunResult(status="approved", ...)
```

The blocking-vs-advisory split inside `run_round` ensures `decision`
is only `rework` for blocking issues, so the harness `_decide`
function still routes correctly.

## Tests

`tests/unit/test_reviewer_agent.py`:

1. `test_reviewer_cross_check_marks_unsupported_claim_advisory` —
   `_ScriptedReviewerRuntime` returns one supported + one unsupported
   verdict; asserts `completed=True`, advisory present with
   `blocking=False`, and v2_verified claim persisted with
   `accuracy=unsupported`
2. `test_reviewer_cross_check_does_not_bump_supported_claim` —
   all-supported verdict; asserts no advisory, claim version unchanged
3. `test_reviewer_skips_cross_check_without_model_runtime` —
   asserts `accuracy` stays `unverified`
4. `test_reviewer_skips_cross_check_when_source_content_missing` —
   sources without `content_ref`; asserts model not called for
   verification

`tests/unit/test_orchestrator.py`:

5. `test_orchestrator_promotes_advisory_feedback_to_caveats` — stub
   harness emits reviewer `decision=stop` with one advisory; asserts
   `status="approved_with_caveats"`, `caveats=[advisory]`,
   `review_feedback=[]`

## Backward compatibility

- `AnalysisClaim.accuracy` defaults to `unverified` — every existing
  fixture and analyst output deserialises unchanged
- `_verify_claim_support` is a no-op when `model_runtime is None`,
  preserving the deterministic / fake-pipeline path used by all 12
  pre-existing reviewer tests
- The reviewer's `decision=stop` now ships advisories in
  `review_feedback`, but advisories all have `blocking=False`. The
  pre-existing contract "any blocking feedback ⇒ rework" still holds
- `approved_with_caveats` consumers (CLI, web dashboard, [[31]])
  don't change — caveats from `unsupported_claim` advisories render
  the same way `format_violation` timeout caveats do

## Related

- [[31-approved-with-caveats]] — the soft terminal state that absorbs
  the advisories
- [[32-model-retry]] — the single batched verification call uses the
  retry policy unchanged
- [[33-global-timeout]] — single-call design (rather than per-claim)
  keeps the verification step inside the wall-clock budget
