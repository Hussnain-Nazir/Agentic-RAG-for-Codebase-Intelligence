# Prism live demo script

This follows `PRISM_SPEC.md` section 35 against `backend/tests/fixtures/demo_repo/`, the current React workspace, and the current REST API. The fixture is a FastAPI, SQLAlchemy, JWT, React, and Vite application with organization registration and user-owned items. The steps require a live GitHub App, two configured OpenAI-compatible model slots, and SerpAPI for the web-search beat. Deterministic tests use mocks and do not substitute for this live walkthrough.

## Preflight

1. Prepare a GitHub repository containing the **contents** of `backend/tests/fixtures/demo_repo/` at its root. Record its owner, repository name, and branch. Do not substitute the Prism repository itself for the fixture.
2. Configure `.env` as in the root README: database credentials, a strong `JWT_SECRET`, `MODEL_A_*`, `MODEL_B_*`, `SERPAPI_API_KEY`, and the GitHub App ID, client ID, client secret, and private-key path. Give the App read-only Contents and Metadata permissions, enable user authorization, and expose `GET /github/callback` at its configured public callback URL. Keep secrets server-side. A 180-second slot timeout may be useful for long Flow Trace runs; this is configuration, not a changed execution bound.
3. Run `docker compose up -d --build` and confirm the three services are healthy with `docker compose ps`. The backend entrypoint applies migrations. Open `http://localhost:5173`, register or log in, and keep the same account for all seven beats.
4. Keep the **Agent Trace** workspace tab available. It shows actual tool calls and model executions. API equivalents are `GET /agent-runs/{run_id}` and `GET /agent-runs/{run_id}/trace` with the signed-in user's bearer token. Do not present a model-written sequence as the trace.

## 1. GitHub integration

1. In the UI choose **Add Repository**, then **Connect GitHub**. This uses authenticated `GET /github/install-url`. Authorize only the fixture repository in the GitHub App installation. The callback is `GET /github/callback` and returns to the frontend.
2. In the GitHub picker, select the installation and find the fixture repository. Show its public/private indicator, select the intended branch, and click **Import**. The picker uses `GET /github/installations`, `GET /github/installations/{installation_id}/repositories`, and the branch-list endpoint; import uses `POST /repositories` with `source_type=github`.
3. Watch the Indexing Status screen until `GET /repositories/{id}/index-status` reports `READY`. Note the repository ID and index version. Open the workspace. If the GitHub callback or import fails, stop and fix that live setup; a ZIP import is a separate fallback demonstration, not proof of GitHub integration.

## 2. Codebase Q&A

1. In **Analyze > Codebase Q&A**, select Model A and ask: "How does this application ensure that an authenticated user can only access and modify their own items? Explain where authentication is checked, how items are filtered for the current user, and how unauthorized update or delete attempts are rejected, citing the relevant files and symbols."
2. Show the answer's evidence chips and open at least one in the Evidence panel. Expected areas include `backend/demo_app/routes/items.py`, `backend/demo_app/security.py`, `backend/demo_app/services.py`, and `backend/demo_app/repositories.py`. The request goes to `POST /repositories/{id}/ask` with `{question, model_slot:"A"}`. Check real file paths and line ranges rather than accepting prose alone.

## 3. Flagship Flow Trace

1. Select **Flow Trace** and ask: "Trace the complete login flow from the user submitting the React login form to the frontend receiving and storing the JWT access token. Show the ordered path through the frontend API client, FastAPI login route, authentication service, user lookup, password verification, JWT creation, and the response back to the React application."
2. The UI calls `POST /repositories/{id}/flow-trace`. Inspect ordered steps and citations. The known source path includes `frontend/src/LoginForm.tsx` (`LoginForm`), `frontend/src/api.ts` (`login`), `backend/demo_app/routes/auth.py` (`login`), `backend/demo_app/services.py` (`authenticate_user`), `backend/demo_app/repositories.py` (`get_user_by_email`), and `backend/demo_app/security.py` (`verify_password`, `create_access_token`). An unproven callback or `setToken` transition must remain unresolved.
3. Open **Agent Trace**, expand details, and show at least three recorded tool calls with timestamps, statuses, and the selected model execution. If the run has fewer calls or is partial, report what it actually did.

## 4. Change Impact

1. Select **Change Impact** and submit: "Suppose we change the User model so that a user can belong to multiple organizations instead of having the single User.organization_id foreign key. What files and symbols in this repository would need to change directly, and what areas would likely be affected indirectly? Include the SQLAlchemy User and Organization relationships, registration schema and registration logic, frontend registration request, seed/setup code, and tests, with repository evidence for every affected area."
2. The UI calls `POST /repositories/{id}/change-impact`. Show separate **Directly affected** and **Likely indirectly affected** sections. Inspect cited `backend/demo_app/models.py`, `backend/demo_app/schemas.py`, `backend/demo_app/services.py`, `backend/demo_app/routes/auth.py`, `frontend/src/api.ts`, `backend/demo_app/seed.py`, and `backend/tests/test_api.py` as returned. Open citations and check the recommended actions and tests-to-inspect fields.
3. Click **Save Finding** if current code evidence is present, then open **Findings**. The UI posts to `POST /repositories/{id}/findings`; the saved title is bounded to 255 characters while the complete requested change remains in finding content. This is a saved finding, not an automatic repository-memory fact.

## 5. Conditional web-search plugin

1. Return to **Analyze > Codebase Q&A**. Ask a repository-related question that needs external status, for example: "Is the JWT library used by this repository deprecated according to current official docs? Compare that current guidance with the stored login code." This goes through the same `POST /repositories/{id}/ask` endpoint. The backend classifies explicit current/official-documentation wording as `EXTERNAL_DOC_QUERY`.
2. Open **Agent Trace** and confirm an actual `search_web` call. Web search runs only when the repository-only evidence is insufficient; if this question has strong repository evidence and no search occurs, use a narrower current external API or deprecation question, and do not claim the plugin ran until the trace shows it. Show a WEB-tagged evidence chip with its external URL separately from CODE evidence. A provider error should appear as a limitation, not as a fabricated web citation.
3. Ask an ordinary repository-only question through the same Ask tab, such as "What does `create_access_token` do in this repository?" Verify its trace has no `search_web` call.

## 6. Memory

1. Open the **Memory** workspace tab. A high-confidence Codebase Q&A answer with at least one valid CODE citation can create a repository fact automatically. If no fact was saved by beat 2, ask a focused grounded question such as "How does `create_access_token` issue a JWT?", then refresh Memory. Show the fact, index version, evidence links, and stale indicator if applicable.
2. Ask a follow-up that includes the repository-memory topic keyword, for example "In this repository, how does `create_access_token` fit into login?" Automatic Q&A facts currently use the `repository_qa` topic, and `ContextBuilder` filters memory by topic keywords. Inspect the run's `retrieve_memory` tool result count. To claim meaningful reuse, verify that the saved fact was selected for the follow-up's evidence context or affected the grounded answer; a tool call alone is not proof. The normal Ask endpoint creates a new session per request, so use repository memory for this beat rather than claiming conversation-session reuse.
3. If no eligible high-confidence fact or demonstrated reuse appears with the configured real model, record beat 6 as incomplete. The Findings tab from beat 4 shows saved analysis but is not a substitute for repository-memory reuse.

## 7. Model selection and explicit comparison

1. On **Analyze**, choose Model A for one normal Q&A request, then choose Model B for the same or another grounded repository question. Inspect each Agent Trace: a normal run should have only the chosen slot's generation. The selection remains while visiting Code, Agent Trace, Memory, and Findings in the same workspace.
2. Enter "How does `authenticate_user` verify a password?" and click **Ask & Compare**. The UI calls `POST /repositories/{id}/compare-models` with `{question}`. Show both peer cards, their model names, latency, token counts when supplied, validation status, and any error. Both receive one shared `EvidenceContext` and the same instructions. There is no judge model and no automatic winner.

After the walkthrough, retain the Agent Trace run IDs and the recording. A failed live step is a result to report, not a reason to substitute mock output or change the fixture.
