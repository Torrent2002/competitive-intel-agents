# 28 Report Export Package

## Goal

Produce a polished report bundle suitable for review, sharing, and interview demos.

## Scope

In scope:

- Markdown report.
- JSON artifact bundle.
- Provenance appendix.
- Reviewer feedback appendix when present.
- Optional HTML export.
- CLI command:
  - `competitive-intel export --run-id <id> --format markdown|html|json`

Out of scope:

- PDF rendering unless explicitly added later.
- Slide deck generation.

## Tests

- Export includes report sections.
- Export includes source and claim ids.
- Export includes provenance appendix when available.
- Export fails clearly for missing run/report.

## Done Criteria

- Final output is inspectable by non-developers.
- Evidence links travel with the report.
