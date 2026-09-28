# Phase 27 security and privacy review

Scope: PRISM_SPEC.md sections 28.1, 28.2, and 28.3. All tests use isolated
SQLite storage, synthetic credentials, mocked GitHub/web transports, and
MockProvider. No live credential or repository was used in this review.

## Threat coverage

| Threat | Checked mitigation and automated proof | Fix |
| --- | --- | --- |
| Cross-user repository access | `test_security_review.py::test_every_registered_tool_rejects_nonowner_before_execution` invokes every registered tool with missing identity and another user's identity. `test_every_repository_route_rejects_nonowner` enumerates every Prism repository route and requires 403 before domain execution. | `search_web.execute` now requires a repository context and checks ownership before cache or provider access. |
| Private repository confidentiality | The two-repository test below checks stored-data isolation. `test_github_integration.py::test_installation_token_is_retrieved_and_cached`, `test_repository_listing_follows_link_header_pagination`, and `test_pagination_rejects_external_link_before_sending_installation_credential` verify installation authentication and prevent credentials reaching another origin. | None. GitHub App registration must retain read-only Contents and Metadata permissions as documented in setup; tests do not contact GitHub to inspect a live App. |
| GitHub App key/token exposure | GitHub routes return only the declared installation/repository metadata fields. GitHub token cache is process-local. The token/pagination tests above and `test_github_routes_persist_and_list_installation_and_repositories` cover those boundaries. Hook redaction test below covers GitHub credentials in arguments. | None. |
| Model/web-search API key exposure | `test_llm.py::test_models_config_requires_authentication_and_returns_names_only` proves only model names are public. `test_openai_compatible_provider_sanitizes_provider_error_details` and `test_web_plugin.py::test_serpapi_success_maps_documented_organic_results` cover provider errors/cache metadata. Phase 27 hook test covers both model slots and SerpAPI arguments. | None. |
| Prompt injection / indirect injection | `test_injection_secret_and_binary_content_cannot_authorize_tools_or_enter_storage` sends an injected comment through real ingestion and Q&A prompt construction, with MockProvider also attempting to return a `save_memory` directive. The tool sequence equals the clean repository's sequence; no save or web tool is triggered. The attack is inside the untrusted evidence zone. Versioned Q&A, flow, impact, and architecture prompts explicitly treat content as data. Existing citation and evaluation adversarial tests reject fabricated authority. | None. Controller decisions do not consume model-generated tool directives. |
| ZIP path traversal / Zip Slip | `test_nested_zip_slip_is_rejected_before_extraction` covers deeply nested, Windows, absolute, and drive-qualified paths. `test_zip_symlink_is_rejected_before_writing` covers symlinks. Existing `test_zip_slip_is_rejected_before_outside_file_is_written` still runs. | None. Validation finishes before extraction starts. |
| Huge upload DoS | `test_high_compression_bomb_hits_uncompressed_cap_before_writing` uses a highly compressed archive over a test uncompressed-size cap. `test_zip_ingestion.py::test_oversized_zip_returns_413_before_extraction` proves upload rejection. Size/file-count limits are checked before writes. | No arbitrary compression-ratio limit was added; the existing hard uncompressed byte cap rejects the bomb. |
| Binary files in model context | The combined ingestion/storage/prompt test includes a binary sentinel, asserts no chunk contains it, and searches every stored table and sent message for it. Existing ZIP classification and bounded-prefix tests also cover binary detection. | None. |
| Secret files in model context | The same test includes synthetic `.env` and PEM data and verifies absence from chunks, prompts, and every persisted table. `test_file_plugin_rejects_secret_names_even_if_a_row_was_inserted` covers a secret filename with a supported extension in an artificially seeded row. | File reading now applies the same secret-filename denylist before loading content. |
| XSS from code/docs | `WorkspacePage.test.tsx::renders script-bearing evidence and file content as escaped text` renders script and event-handler tags in both the citation and file viewer, requires no script/img DOM element, and verifies the execution sentinel remains false. Model answers and saved text also use React text children; no raw HTML renderer or `dangerouslySetInnerHTML` exists. | None. HTML is escaped rather than interpreted as Markdown HTML. |
| SQL injection | `test_backend_sql_sinks_never_receive_interpolated_sql` parses every Python module under `backend/app`, rejects dynamic SQL literal sinks and formatted SQL expressions. Manual search found ORM/parameterized expressions and static SQL literals only. | No interpolated SQL found. |
| Unauthorized repository access via API | The dynamic route inventory test above proves every repository-scoped route rejects the wrong owner. Existing agent-run and GitHub installation/branch ownership tests cover their separately scoped URLs. DELETE lives in `api/routes/repository_data.py`, not the import/sync module. | None. |
| Logging leaks | `test_hook_persistence_redacts_all_configured_credential_key_shapes` verifies persisted arguments redact GitHub tokens, Model A/B keys, SerpAPI keys, and nested private keys, including camelCase/hyphenated names; captured logs contain none of the synthetic values. Existing hook/provider error tests remain in the full suite. | None. |

All Phase 27 backend tests are in `tests/test_security_review.py` unless a
different file is named. Provider-specific tests are mocked; no actual key is
printed or stored by this review.

## Section 28.3 privacy and data handling

- **Access control and isolation:** `test_all_tools_keep_similarly_named_repositories_isolated`
  imports two repositories owned by the same user with identical paths and
  symbols but distinct content and IDs. It invokes all eleven tools and session
  memory, rejecting the other repository's content, index, file, symbol,
  relationship, chunk, and session IDs in each result. Public web cache results
  contain external documentation, not repository content.
- **Bounded external payload:** `test_actual_model_payload_contains_only_bounded_context_for_large_repository`
  runs a real Q&A request for each model slot over 30 large files. The exact
  messages received by MockProvider contain at most 12 evidence items, at most
  24,000 excerpt characters, and an estimated maximum of 6,000 evidence tokens.
  No complete large file or entire repository occurs in those messages. Fixed
  instructions, schemas, and user input are separate from the evidence budget.
- **Persisted data inventory:** `test_persisted_table_inventory_matches_documented_policy_and_known_scaffolds`
  freezes the current 18-table inventory. The policy's repository, index, file,
  chunk, structure, memory, finding, trace, and web-cache tables exist. Accounts,
  sessions, messages, hashed short-lived GitHub installation attempts, and the
  unused Phase 4 `memory_items` scaffold are also expected. The secret sentinel
  test scans every table, including those additional tables, for raw secret and
  binary content. Supplementary-document tables still do not exist; their
  storage and deletion must be tested when implemented.
- **Deletion:** `test_api_completion.py::test_delete_repository_removes_all_existing_dependent_rows`
  performs the real DELETE request and directly counts every existing dependent
  table afterward. Phase 27 extends it to include conversation messages and
  legacy `memory_items`. Files, indexes, chunks, symbols, relationships, memory,
  findings, sessions, messages, runs, tool calls, and model executions all reach
  zero. Supplementary-table absence is explicitly asserted.
- **Revocation versus deletion:** GitHub access loss retains a read-only index
  and prevents synchronization; existing GitHub lifecycle tests cover this.
  Explicit repository deletion cascades. A user-facing installation disconnect
  endpoint is not implemented and was not added by this phase.

## Verification

Run the complete backend suite by passing all top-level `tests/test_*.py` files
plus `tests/eval/test_evaluation_thresholds.py` and the demo repository's
`backend/tests/test_api.py`. This avoids pytest descending into pre-existing
inaccessible temporary folders while still running every test file. Run
`npm test` and `npm run build` from the main frontend, and `npm run build` from
the demo fixture frontend. Results are recorded in the Phase 27 log after the
final run. No live model or web/GitHub credential is required.

Final results on 2026-09-26: **301 backend tests passed, 2 skipped** (the
opt-in PostgreSQL/pgvector cases requiring `PRISM_TEST_POSTGRES_URL`), including
17 Phase 27 security cases and the expanded DELETE test. **21 frontend tests
passed**, including escaped XSS rendering. Main and demo frontend production
builds passed. Core-module coverage is **92.52%**. No schema migration was needed.
