# Deterministic repository evaluation

Run `python tests/eval/run_evaluation.py` from `backend/` to index the complete
`tests/fixtures/demo_repo` source and write [report.json](report.json). Run
`pytest -p no:cacheprovider tests/eval/test_evaluation_thresholds.py` for the
acceptance gate. The recorded [questions.json](questions.json) contains 25
questions: 6 symbol lookups, 6 Q&A, 3 architecture, 5 flow traces, and 5
change-impact analyses.

The script uses Prism's actual upload-source ingestion, Tree-sitter parsing,
chunking, index rows, hybrid retrieval, tool registry, and single controller.
Its local 384-dimensional hash embedding is deterministic and requires no model
download. The generative step uses `MockProvider`, whose response quotes the
provided evidence or copies observed graph facts. These choices keep the normal
suite independent of network and model credentials. They do not measure the
quality of the production embedding model or hosted models; those need a
separate manual run. `python tests/eval/run_evaluation.py --real-embeddings`
uses the configured `LocalEmbeddingProvider` and writes a separate
`report_real_embeddings.json`; it is not invoked by automated tests and may
need the model to be downloaded locally.

Ground truth is written before execution in `questions.json`. Retrieval Hit@12,
expected-file and symbol recall, ordered flow-step recall, direct and indirect
impact recall and precision, citation validity using `validate_citations`,
grounded-response rate, invalid-reference rate, tool-call count, and wall-clock
latency are computed from indexed rows, tool observations, validated responses,
and the recorded expected sets. No LLM judge is used. A response with an
unsupported claim, fabricated file/symbol/line, invalid citation, or resolved
transition absent from observed graph fails the gate even if aggregate rates
remain high. Unresolved flow links are permitted and reduce step recall when
an expected definition is not reached.

Current measured summary: 25 questions, Hit@12 100%, expected file/symbol
recall 100%, citation validity 100%, grounded responses 100%, invalid
references 0%, ordered flow-step recall 93.33%, direct-impact recall and
precision 100%, indirect-impact recall 100% and precision 90%. Core coverage
is 92.07% on the runnable subset; see [COVERAGE.md](COVERAGE.md) for the
command and its environment limit.
