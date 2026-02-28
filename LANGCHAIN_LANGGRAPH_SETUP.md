# LangChain / LangGraph Integration

## What is implemented

- `AI advice` endpoint now supports engine routing:
  - `classic`: existing direct LLM call.
  - `langgraph`: multi-step workflow (market evidence retrieval -> profile summary -> gap analysis -> final advice).
  - `auto`: uses LangGraph when `AI_LANGGRAPH_ENABLED=true`, otherwise fallback to classic.
- Existing API contract is still compatible.
- LangGraph flow now pulls ES-based market evidence (`job stats` + `skill cloud`) as explainable context.

## Files changed

- `jobCollectionWebApi/services/ai_service.py`
- `jobCollectionWebApi/schemas/analysis.py`
- `jobCollectionWebApi/api/v1/endpoints/analysis_controller.py`
- `jobCollectionWebApi/config.py`
- `requirements.txt`

## New config

Add to `.env`:

```env
AI_LANGGRAPH_ENABLED=true
AI_LANGCHAIN_TEMPERATURE=0.6
AI_LANGCHAIN_TIMEOUT_SECONDS=60
```

## API usage

Endpoint:

`POST /api/v1/analysis/ai/advice`

Request body:

```json
{
  "major_name": "Computer Science",
  "skills": ["Python", "FastAPI", "SQL"],
  "engine": "langgraph"
}
```

`engine` options:

- `auto` (default)
- `classic`
- `langgraph`

## Resume-ready highlights

- Designed a **LangGraph state workflow** for career advisory generation.
- Added **engine routing and graceful fallback** from LangGraph to classic LLM flow.
- Kept endpoint contract stable while enabling **incremental AI orchestration upgrade**.
- Added centralized configuration to control **latency/temperature/runtime behavior**.

## Suggested next LangGraph upgrades

1. Add a scoring node that outputs confidence and evidence coverage.
2. Add a human-in-the-loop interrupt node for premium paid users.
3. Persist graph run traces and token usage for admin billing insights.
4. Add evaluation datasets and automatic prompt regression checks.
