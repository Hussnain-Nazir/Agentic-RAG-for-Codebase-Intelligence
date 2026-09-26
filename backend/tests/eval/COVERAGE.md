# Core coverage report

Measured on 2026-09-25 with Python 3.14 and pytest-cov. The command covered
`app.retrieval`, `app.evidence`, `app.agent`, `app.tools`, `app.memory`,
`app.parsing`, and `app.chunking`:

```powershell
$testFiles = @(Get-ChildItem -LiteralPath tests -File -Filter 'test_*.py' |
    Where-Object { $_.Name -notin @('test_flow_trace.py','test_zip_ingestion.py') } |
    ForEach-Object { $_.FullName })
$testFiles += (Resolve-Path 'tests/eval/test_evaluation_thresholds.py').Path
$testFiles += (Resolve-Path 'tests/fixtures/demo_repo/backend/tests/test_api.py').Path
pytest -p no:cacheprovider -q --disable-warnings `
    --cov=app.retrieval --cov=app.evidence --cov=app.agent `
    --cov=app.tools --cov=app.memory --cov=app.parsing --cov=app.chunking `
    --cov-report=term --cov-report=json:tests/eval/coverage.json $testFiles
```

Result: **2,902 statements, 230 missed, 92.07% coverage**; 248 tests passed
and 2 opt-in PostgreSQL/pgvector tests skipped. This exceeds the specification's
approximately 70% core-logic target. Full line details are in [coverage.json](coverage.json).

This run excluded `test_flow_trace.py` and `test_zip_ingestion.py` because their
temporary-directory fixtures cannot write under this session's Windows sandbox.
Their two tests that do not need temporary directories passed separately.
The full suite still needs a run with normal temporary-directory access before
Phase 26 can be marked complete.
