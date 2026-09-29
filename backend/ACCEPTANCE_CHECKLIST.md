# MVP acceptance checklist

This follows `PRISM_SPEC.md` section 34 item by item. `Tested` means a deterministic test or checked report exists in this repository. `Manual` means the listed live step still needs a person and credentials. `Partial` identifies a narrower implementation or a missing verification. Test names below are in `backend/tests/` unless prefixed with `frontend/`; the report and scripts are repository files, not claims about the current deployment. The opt-in PostgreSQL tests require `PRISM_TEST_POSTGRES_URL`. A passing mock test does not prove a live provider is configured.

| # | Criterion | Status | Checkable evidence or required step |
| ---: | --- | --- | --- |
| 1 | User authentication | Tested | `test_auth.py::test_successful_registration_hashes_password`, `test_successful_login`, and protected-route tests. |
| 2 | Install/connect Prism GitHub App | Manual | `test_github_integration.py::test_github_routes_persist_and_list_installation_and_repositories` mocks the flow; follow `DEMO_SCRIPT.md` beat 1 with a live read-only App and callback. |
| 3 | List installation-authorized repositories | Tested, live check pending | `test_github_integration.py::test_repository_listing_follows_link_header_pagination`; inspect the picker in demo beat 1. |
| 4 | Select authorized public/private repository | Tested, live check pending | `frontend/src/pages/GitHubPicker/GitHubPickerPage.tsx` filters visibility and selects a repository; test `test_branch_picker_route_checks_installation_and_repository_access`; exercise both visibility types manually. |
| 5 | Select branch | Tested, live check pending | `test_branch_picker_route_checks_installation_and_repository_access` and GitHub picker branch selector; choose the fixture branch in beat 1. |
| 6 | Ingest and index GitHub repository | Tested, live check pending | `test_github_import_uses_shared_normalization_and_persists_blob_shas`; observe READY in beat 1. |
| 7 | Upload ZIP | Tested | `test_zip_ingestion.py::test_clean_fixture_normalizes_expected_repository_files`; stack smoke script imports a ZIP. |
| 8 | Shared downstream GitHub/ZIP pipeline | Tested | `test_github_import_uses_shared_normalization_and_persists_blob_shas` and `backend/app/ingestion/pipeline.py`. |
| 9 | Tree-sitter structural parsing | Tested | `test_parsing.py::test_python_extracts_functions_methods_class_route_and_relationships` and JS/TS parser tests. |
| 10 | Python, JS, TS, JSX, TSX support | Tested | `test_parsing.py` parser cases and `backend/app/ingestion/pipeline.py` extension mapping. |
| 11 | Structural chunks with file/symbol/line metadata | Tested | `test_chunking.py::test_large_function_splits_with_overlap_and_full_symbol_metadata` and persistence test. |
| 12 | Local embeddings | Tested with fake provider; live load pending | `test_embeddings.py::test_local_provider_calls_model_in_batches_of_32`; manually index with configured `LocalEmbeddingProvider`. |
| 13 | PostgreSQL/pgvector embedding storage and search | Partial | Alembic revisions `0007_add_code_chunks.py` and `0008_add_embedding_indexes.py`; run opt-in `test_embeddings.py::test_postgres_pgvector_search_orders_and_limits_scoped_results` with `PRISM_TEST_POSTGRES_URL`. |
| 14 | Lexical retrieval | Tested | `test_lexical_symbol_retrieval.py::test_lexical_search_ranks_exact_phrase_above_unrelated_chunk`; PostgreSQL generated search vector is in revision `0009`. |
| 15 | Exact symbol retrieval | Tested | `test_lexical_symbol_retrieval.py::test_symbol_search_finds_exact_name`. |
| 16 | Hybrid signal merge | Tested | `test_hybrid_retrieval.py::test_merge_uses_frozen_signal_weights` and deterministic retriever test. |
| 17 | Real file/line evidence | Tested | `test_codebase_qa.py::test_repository_qa_returns_grounded_answer_and_persisted_trace`. |
| 18 | Repository question | Tested | Same Q&A endpoint test and `frontend/src/pages/Workspace/WorkspacePage.test.tsx` analysis test. |
| 19 | Direct query skips model | Tested | `test_agent_orchestration.py::test_direct_tasks_make_zero_model_calls`. |
| 20 | Bounded multi-step tools | Tested | `test_agent_orchestration.py::test_tool_iteration_bound_stops_at_twelve` and other bound tests; inspect Agent Trace in beat 3. |
| 21 | Multi-file Flow Trace | Tested | `test_demo_analysis_regression.py::test_full_login_flow_starts_in_frontend_and_keeps_unproven_links_unresolved`. |
| 22 | Unresolved rather than fabricated links | Tested | `test_flow_trace.py::test_broken_flow_marks_transition_unresolved` and `test_unbacked_model_transition_is_rejected_by_deterministic_fallback`. |
| 23 | Change Impact | Tested | `test_change_impact.py::test_change_impact_separates_definition_and_consumers`. |
| 24 | Direct and likely indirect impacts separate | Tested | Same Change Impact test and `backend/tests/eval/report.json` impact metrics. |
| 25 | Session/repository/findings memory, meaningfully reused | Partial | `test_memory.py::test_session_memory_returns_last_three_relevant_exchanges`, repository memory and finding tests. Controller retrieves repository memory, but `ContextBuilder` selects it by topic keyword; automatic Q&A facts use the `repository_qa` topic. A live follow-up proving meaningful reuse still needs beat 6. Session memory is implemented but the normal Ask path does not demonstrate reuse. |
| 26 | Repository memory provenance | Tested | `test_memory.py::test_merged_evidence_saves_durable_chunks_and_stales_on_file_change`. |
| 27 | New/changed/deleted sync | Tested | `test_incremental_sync.py::test_changed_new_deleted_sync_rebuilds_and_stales_memory`. |
| 28 | Changed evidence stales memory | Tested | Same sync test and `test_memory.py::test_invalidate_stale_only_marks_changed_file_memories`. |
| 29 | File-reading plugin | Tested | `test_file_plugin.py::test_valid_file_and_range_reads_return_exact_content` and path-error tests. |
| 30 | Conditional web search through `/ask` | Tested with fake provider; live check pending | `test_codebase_qa.py::test_external_doc_question_returns_tagged_sources_and_bounded_run` and `test_ordinary_qa_does_not_search_web`; beat 5 needs SerpAPI credentials. |
| 31 | WEB evidence distinct | Tested | Same external-doc test and `frontend/src/pages/Workspace/WorkspacePage.test.tsx` external-evidence drawer case. |
| 32 | Pre/post hooks | Tested | `test_agent_skeleton.py` hook recording and `test_agent_orchestration.py::test_repository_qa_calls_one_model_and_persists_trace`. |
| 33 | Persisted runs, tools, models | Tested | `test_codebase_qa.py::test_repository_qa_returns_grounded_answer_and_persisted_trace`. |
| 34 | Inspect Agent Trace | Tested | `test_api_completion.py::test_agent_run_detail_and_ordered_trace` and `frontend/src/components/workspace/AgentTrace.tsx`. |
| 35 | Model A env configuration | Tested, live check pending | `test_llm.py::test_model_factories_use_independent_slot_configuration`; configure and invoke A in beat 7. |
| 36 | Model B env configuration | Tested, live check pending | Same factory test; configure and invoke B in beat 7. |
| 37 | No hard-coded hosted provider in business logic | Tested by inspection | `backend/app/llm/factory.py` constructs both `OpenAICompatibleProvider` slots from settings; `test_model_factories_use_independent_slot_configuration`. |
| 38 | User selects A or B | Tested | `frontend/src/pages/Workspace/WorkspacePage.test.tsx` verifies Model B stays selected across workspace tabs and is sent on follow-up. |
| 39 | Normal request invokes selected model only | Tested | `test_agent_orchestration.py::test_normal_requests_use_each_selected_slot_timeout_without_fallback`. |
| 40 | No automatic fallback | Tested | `test_agent_orchestration.py::test_selected_model_failure_is_traced_without_fallback`. |
| 41 | Explicit comparison uses same context/instructions | Tested | `test_model_comparison.py::test_compare_models_shares_exact_prompt_and_persists_peer_results`. |
| 42 | Deterministic MockProvider | Tested | `test_llm.py::test_mock_provider_returns_canned_responses_in_order`. |
| 43 | Embeddings separate from A/B | Tested by architecture | `backend/app/embeddings/base.py`, `backend/app/llm/base.py`, and `test_embeddings.py` fake-embedding tests. |
| 44 | Pydantic schemas for important outputs | Tested | `test_structured_output_validation.py::test_well_formed_response_for_every_schema_passes`. |
| 45 | Structured output validation | Tested | `test_architecture.py::test_architecture_repair_is_bounded_to_two` and schema validation tests. |
| 46 | Citation validation | Tested | `test_structured_output_validation.py::test_nonexistent_evidence_id_is_removed_and_downgraded` and stale-version test. |
| 47 | Untrusted prompt-injection handling | Tested | `test_security_review.py::test_injection_secret_and_binary_content_cannot_authorize_tools_or_enter_storage`. |
| 48 | Cross-user isolation | Tested | `test_security_review.py::test_every_repository_route_rejects_nonowner` and `test_every_registered_tool_rejects_nonowner_before_execution`. |
| 49 | Secret files excluded from model context | Tested | `test_injection_secret_and_binary_content_cannot_authorize_tools_or_enter_storage` scans stored rows and model messages. |
| 50 | Full end-to-end workflow | Tested historically; rerun for deployment | `backend/scripts/smoke_test_stack.py` and Phase 28 `prompts.md` result cover register, ZIP import, READY, real-model Q&A, and trace. |
| 51 | About 70% core coverage | Measured historically | `backend/tests/eval/COVERAGE.md` records 92.52% on 2026-09-26; rerun coverage for a current figure. |
| 52 | Containerized/deployable | Tested historically; rerun for deployment | `docker-compose.yml`, `docker-compose.prod.yml`, `backend/entrypoint.sh`, and Phase 28 stack smoke result. |
| 53 | Maintained `prompts.md` | Documented, historical gaps flagged | Phase entries through 28 and this Phase 29 review; fields lacking first-hand acceptance evidence are marked manual. |
| 54 | Recorded final live multi-step demo | Manual gap | Run and record all seven beats in `DEMO_SCRIPT.md`; no recording is in this repository. |
| 55 | Three flagship deterministic criteria | Tested | `tests/eval/test_evaluation_thresholds.py::test_demo_evaluation_clears_ground_truth_thresholds` and 26-question `tests/eval/report.json`, including zero invalid references. |
| 56 | 2,000-file target, warning, and hard bounds | Partial | `test_zip_ingestion.py::test_repository_over_mvp_target_is_ready_with_size_warning`, small fixture import, and oversized ZIP/Zip Slip tests; UI notice is in `frontend/src/pages/IndexingStatus/IndexingStatusPage.tsx`. A full 500 MB/20,000-file live boundary and answer-quality check at scale are not recorded. |
| 57 | No stretch-goal feature in MVP | Inspected | Section 36 features are absent from routes and workspace; `get_review_history` is a tool over findings, not a review endpoint. Recheck before release. |
| 58 | No secret-bearing data in persisted chunks or model payload | Partial | `test_security_review.py::test_injection_secret_and_binary_content_cannot_authorize_tools_or_enter_storage` checks existing tables and both slots' payloads. `supplementary_document_chunks` does not exist, so its portion cannot be tested. |
| 59 | Repository deletion cascades all indexed data | Partial | `test_api_completion.py::test_delete_repository_removes_all_existing_dependent_rows` queries all existing dependent tables after DELETE. Supplementary-document tables do not exist; installation disconnect is not implemented. |
| 60 | Repository ID isolation in API/tool/retrieval results | Tested | `test_security_review.py::test_all_tools_keep_similarly_named_repositories_isolated`, route ownership inventory, and retrieval isolation tests. |

## Open acceptance work

- Complete the live GitHub App, both model slots, conditional web search, and seven-beat recorded demo on the target environment.
- Run the opt-in PostgreSQL/pgvector integration tests and rerun the Compose smoke test after deployment.
- Decide whether supplementary-document ingestion and installation disconnect are required before declaring every section 34 criterion satisfied. The corresponding tables and disconnect endpoint are absent today.
- Demonstrate meaningful memory reuse in a follow-up, verify the full size boundary at the intended scale, and update the historical coverage measurement if a current percentage is required.
