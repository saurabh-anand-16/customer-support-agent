# Langfuse notes for phase 6 (tracing)

Collected 2026-11-18 from the Langfuse docs and from installing and running the SDK in a sandbox.
**Not tested against a real Langfuse server.** The sandbox had no account and no route to Langfuse Cloud. Everything marked "tested" ran locally with a fake exporter or an unreachable host.

## 1. Versions (this changed since my earlier plan)

- The newest Python SDK on PyPI is **5.2.0**. My earlier knowledge was of v3. Pin the version in `requirements-agent.txt`.
- The docs say **Python SDK v5 needs Langfuse server v4**. Cloud is fine. Self-hosting needs server 4.59.0 or newer. For a self-hosted v3 server, use SDK v4.
- Python 3.11 or newer is what the LangGraph page asks for. Our sandbox test ran on Python 3.13.
- The SDK is built on OpenTelemetry. It installs `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `httpx`, `pydantic`, `wrapt`, `backoff`. Check for clashes with our pinned packages before adding it.

## 2. Setup

- Install: `pip install langfuse`
- Environment variables (go in `.env`, never in chat or git):
  - `LANGFUSE_PUBLIC_KEY` (starts `pk-lf-`)
  - `LANGFUSE_SECRET_KEY` (starts `sk-lf-`)
  - `LANGFUSE_BASE_URL` (default is the EU cloud, `https://cloud.langfuse.com`; there are US, Japan and HIPAA regions, and self-hosted needs its own URL)
  - The older name `LANGFUSE_HOST` appears in old tutorials. The constructor still accepts a `host` argument, but use `LANGFUSE_BASE_URL`.
  - Optional: `LANGFUSE_TRACING_ENVIRONMENT` (for example `development`).
- `from langfuse import get_client` then `lf = get_client()` reads the variables. The client is a singleton. A second `Langfuse(...)` with the same public key reuses the first and ignores new arguments.
- `lf.auth_check()` returns true or false. Use it in a setup script, not on every turn.
- Short scripts must call `lf.flush()` before exit. Long-running apps (Streamlit) do not.

## 3. Constructor options (read from the installed SDK 5.2.0)

`Langfuse(public_key, secret_key, base_url, host, timeout, httpx_client, debug, tracing_enabled=True, flush_at, flush_interval, environment, release, media_upload_thread_count, sample_rate, mask, mask_otel_spans, should_export_span, additional_headers, tracer_provider, id_generator, span_exporter, otel_compression, skills)`

Useful for us: `tracing_enabled` (the on/off switch), `environment`, `release` (put the git commit here), `sample_rate`, `mask`, `timeout`, `flush_at`, `flush_interval`, `debug`.

## 4. Recording things

- Decorator: `@observe(name=..., as_type=..., capture_input=..., capture_output=...)`. Turn off capture for anything that holds customer data.
- Context manager: `lf.start_as_current_observation(as_type=..., name=..., input=..., output=..., metadata=..., level=..., status_message=..., model=..., model_parameters=..., usage_details=..., cost_details=...)`. Call `.update(...)` on the object to add output later.
- Observation types: `span`, `generation`, `embedding`, `agent`, `tool`, `chain`, `retriever`, `evaluator`, `guardrail`, and `event` (through `lf.create_event(name=..., metadata=...)`).
- Trace-wide fields: `with propagate_attributes(user_id=..., session_id=..., tags=[...], metadata={...}, version=..., trace_name=..., environment=...):` around the turn. Every observation inside gets them.
- `lf.get_current_trace_id()` and `lf.get_trace_url(trace_id=...)` give a link to a trace. The Developer page can show "open in Langfuse" with that.
- Scores: `lf.create_score(name=..., value=..., trace_id=..., observation_id=..., data_type="NUMERIC"|"CATEGORICAL"|"BOOLEAN"|"TEXT"|"CORRECTION", comment=..., metadata=...)`. Scores count as billable units.
- The docs say trace-level input and output is **deprecated in Langfuse v4**. Put the turn's input and output on the root observation.

## 5. Mapping from our trace (my plan)

| Our trace | Langfuse |
| --- | --- |
| One turn | One trace, root observation `turn` (span or agent) |
| Conversation | `session_id` (the app's session id) |
| Customer | `user_id` (hashed, see section 7) |
| Router call, branch model calls | `generation`, with `model`, `usage_details` |
| Tool calls (`get_order`, `check_eligibility`, ...) | `tool` |
| `search_policy` and the passages | `retriever`, index fingerprint in `metadata` |
| Each `trace["checks"]` entry | `event` named `check:<name>` with passed and reason in `metadata`, or a score |
| Review queue write, confirm step, writer call | `tool` or `event` |

## 6. What I tested (SDK 5.2.0, fake exporter)

- **No keys:** the client prints "initialized without public_key. Client will be disabled" and the app keeps working. A decorated function returned its value normally.
- **Unreachable server:** sending failed with "Connection refused ... will be dropped" as a log message. It did not raise.
- **Structure:** a nested turn produced 5 spans with the right parent, observation types, model name, usage, and trace attributes on every span (`session.id`, `user.id`, `langfuse.trace.name`, tags, environment, release).
- **`mask` works on input and output text.** My test function replaced `C0076` inside a message with `[CUSTOMER]`.
- **`mask` does NOT cover `user_id`.** The span still carried `user.id = C0076`. We must hash the customer id ourselves before passing it.

## 7. Privacy rules for our app

- Hash `customer_id` before it becomes `user_id` (for example a keyed hash from a secret in `.env`).
- Pass a `mask` function that removes customer ids, phone numbers and emails from every input and output.
- Never log keys, `.env`, or the tool schemas' hidden fields.
- Customer messages and order details do go to Langfuse's servers when it is on. Say so in the README.
- The local trace file is the primary record. Langfuse is a copy.

## 8. Failure rules

- Tracing must never break a chat. The tests above show the SDK itself does not raise, but wrap our own tracing calls in try/except anyway.
- Add a test with `tracing_enabled=False` and a test with no keys.
- Keep the SDK's sending quick: set a short `timeout`, and flush in the background, never inside the reply path.

## 9. Integrations

- **OpenAI wrapper:** `from langfuse.openai import OpenAI` is a drop-in replacement that records each model call. It exists in 5.2.0. We call OpenAI through our own wrapper in `agent/llm.py`, so one import there could cover every call. Check that it does not capture the system prompts' hidden fields.
- **LangGraph:** `from langfuse.langchain import CallbackHandler`, passed as `config={"callbacks": [handler]}`. It needs `langchain-core` 1.0 or newer, which we do not have installed (the import failed in my test). It would see the graph's nodes but not our own model and tool calls. My plan is **manual instrumentation** with the context managers above, which is more precise and adds no package.
- The docs note that each graph invocation makes a new trace, so one trace per turn matches what we want.

## 10. Free plan (Cloud Hobby), from the pricing page

- Price: free, no credit card. 50,000 units a month, and no extra usage can be bought on Hobby.
- A unit is "any tracing data point": each trace, each observation (span, generation, event) and each score.
- 30 days of history, 2 users, unlimited projects.
- Rate limits: ingestion 1,000 requests a minute, general API 30 a minute.
- Support from the community only. No data-retention control, no SSO.
- Paid: Core $29 a month (100k units, 90 days), Pro $199 a month, Enterprise $2,499 a month.
- **Our budget:** a turn with 3 model calls, 3 tool calls, 1 retrieval, 6 checks is about 15 units. So the free plan covers roughly 3,000 turns a month. Fine for a demo and the eval runs. Phase 10's full eval (hundreds of cases) could use a large share, so keep the sample rate or the switch in mind.
- A public demo that anyone can use would burn units. Turn Langfuse off in the deployed demo, or sample it.

## 11. Sources

- Langfuse SDK setup: https://langfuse.com/docs/observability/sdk/python/setup
- Langfuse LangGraph integration: https://langfuse.com/integrations/frameworks/langgraph
- Langfuse pricing: https://langfuse.com/pricing
- SDK read directly from the installed package, version 5.2.0.
