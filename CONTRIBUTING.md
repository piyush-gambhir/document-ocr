# Contributing

Contributions are welcome.

## Development

Requirements:

- Python 3.14
- Node.js 22 or later
- [uv](https://docs.astral.sh/uv/)

```bash
make install
make test
make build
```

Keep changes focused, add tests for changed behavior, and update the public
types and documentation when the response schema changes.

## Test-data rules

Do not commit real or publicly downloaded identity documents. New image
fixtures must be generated, contain fictitious data, and carry a prominent
`SPECIMEN — NOT A REAL ID` watermark. Never put personal data in issue reports,
snapshots, logs, or commit messages.

Private accuracy datasets can be placed in `benchmark-data/`, which is ignored
by Git. Non-passport datasets must follow
[`benchmarks/KYC_DATASET.md`](benchmarks/KYC_DATASET.md): use the versioned
manifest, record design/year/language/capture-quality slices, and keep the
locked release split separate from tuning data.

## Pull requests

Explain the behavior being changed, the document layouts considered, and the
validation performed. Run both Python and TypeScript tests before requesting
review.
