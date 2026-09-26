# Core coverage report

Measured on 2026-09-26 with Python 3.14 and pytest-cov. The command covered
`app.retrieval`, `app.evidence`, `app.agent`, `app.tools`, `app.memory`,
`app.parsing`, and `app.chunking`:

```powershell
$testFiles = @(Get-ChildItem -LiteralPath tests -File -Filter 'test_*.py' |
    ForEach-Object { $_.FullName })
$testFiles += (Resolve-Path 'tests/eval/test_evaluation_thresholds.py').Path
$testFiles += (Resolve-Path 'tests/fixtures/demo_repo/backend/tests/test_api.py').Path
pytest -p no:cacheprovider -q --disable-warnings `
    --cov=app.retrieval --cov=app.evidence --cov=app.agent `
    --cov=app.tools --cov=app.memory --cov=app.parsing --cov=app.chunking `
    --cov-report=term --cov-report=json:tests/eval/coverage.json $testFiles
```

Result: **2,902 statements, 217 missed, 92.52% coverage**; 301 tests passed
and 2 opt-in PostgreSQL/pgvector tests skipped. This exceeds the specification's
approximately 70% core-logic target. Full line details are in [coverage.json](coverage.json).

This full run includes every backend test file, including flow/ZIP temporary-
directory tests, Phase 27 security tests, evaluation thresholds, and the demo
repository's own tests. It supersedes the limited 2026-09-25 run. Explicit file
arguments avoid collecting unrelated inaccessible temporary folders.
