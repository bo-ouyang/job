"""
Prometheus custom metrics for the Job Collection Platform.

Exposes business-level gauges and counters beyond what the default
HTTP instrumentator provides:
  - Circuit Breaker state / failure count
  - Celery task counters (submitted from API side)
  - AI billing counters
  - Active WebSocket connections
  - DB / ES / Redis health gauges
"""

from prometheus_client import Counter, Gauge, Histogram, Info

# ── Application Info ─────────────────────────────────────────
app_info = Info("job_platform", "Job Collection Platform metadata")
app_info.info({"version": "1.0.0", "service": "jobCollectionWebApi"})

# ── Circuit Breaker ──────────────────────────────────────────
circuit_breaker_state = Gauge(
    "circuit_breaker_state",
    "Current state of the AI circuit breaker (0=closed, 1=half_open, 2=open)",
    ["breaker_name"],
)

circuit_breaker_failures = Gauge(
    "circuit_breaker_failure_count",
    "Consecutive failure count of circuit breaker",
    ["breaker_name"],
)

circuit_breaker_trips = Counter(
    "circuit_breaker_trips_total",
    "Total number of times the circuit breaker tripped to OPEN",
    ["breaker_name"],
)

# ── AI / LLM ────────────────────────────────────────────────
ai_calls_total = Counter(
    "ai_llm_calls_total",
    "Total LLM API calls made",
    ["method", "status"],  # method: langchain/http, status: success/failure/circuit_open
)

ai_call_duration = Histogram(
    "ai_llm_call_duration_seconds",
    "Duration of LLM API calls in seconds",
    ["method"],
    buckets=[0.5, 1, 2, 5, 10, 20, 30, 60, 120],
)

ai_cache_hits = Counter(
    "ai_cache_hits_total",
    "Number of AI result cache hits",
    ["feature"],  # career_advice / career_compass
)

# ── Celery Tasks (submitted from API side) ───────────────────
celery_tasks_submitted = Counter(
    "celery_tasks_submitted_total",
    "Tasks submitted to Celery from the API",
    ["task_name", "queue"],
)

# ── AI Billing ───────────────────────────────────────────────
ai_billing_charges = Counter(
    "ai_billing_charges_total",
    "Total AI billing charge events",
    ["feature"],
)

ai_billing_amount = Counter(
    "ai_billing_amount_total",
    "Total AI billing amount charged (in credits)",
    ["feature"],
)

ai_billing_rejections = Counter(
    "ai_billing_rejections_total",
    "Total AI billing rejections (insufficient balance / rate limited)",
    ["feature", "reason"],  # reason: balance / rate_limit
)

# ── AI Task Lifecycle ────────────────────────────────────────
ai_task_created = Counter(
    "ai_task_created_total",
    "Total AI tasks created",
    ["feature"],
)

ai_task_completed = Counter(
    "ai_task_completed_total",
    "Total AI tasks completed successfully",
    ["feature"],
)

ai_task_failed = Counter(
    "ai_task_failed_total",
    "Total AI tasks failed",
    ["feature"],
)

ai_task_rejected = Counter(
    "ai_task_rejected_total",
    "Total AI tasks rejected due to concurrency lock",
    ["feature"],
)

ai_task_duration = Histogram(
    "ai_task_duration_seconds",
    "End-to-end AI task execution time in seconds",
    ["feature"],
    buckets=[1, 2, 5, 10, 20, 30, 60, 120, 300],
)

ai_task_dedup_hits = Counter(
    "ai_task_dedup_hits_total",
    "Total AI task deduplication cache hits (same params reuse)",
    ["feature"],
)

# ── WebSocket ────────────────────────────────────────────────
ws_connections_active = Gauge(
    "ws_connections_active",
    "Number of active WebSocket connections",
)

# ── Infrastructure Health ────────────────────────────────────
infra_health = Gauge(
    "infra_component_healthy",
    "Health status of infrastructure components (1=healthy, 0=unhealthy)",
    ["component"],  # database / elasticsearch / redis
)

# ── Career Agent ─────────────────────────────────────────────
agent_runs_created = Counter(
    "agent_runs_created_total",
    "Career Agent runs accepted",
    ["source"],
)
agent_runs_completed = Counter(
    "agent_runs_completed_total",
    "Career Agent runs completed",
)
agent_runs_failed = Counter(
    "agent_runs_failed_total",
    "Career Agent runs failed",
    ["failure_kind"],
)
agent_runs_cancelled = Counter(
    "agent_runs_cancelled_total",
    "Career Agent runs cancelled",
)
agent_run_duration = Histogram(
    "agent_run_duration_seconds",
    "Career Agent end-to-end runtime duration",
    buckets=[1, 2, 5, 10, 20, 30, 45, 60, 90],
)
agent_first_event_latency = Histogram(
    "agent_first_event_latency_seconds",
    "Latency from AgentRun creation to first event",
    buckets=[0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
)
agent_tool_calls = Counter(
    "agent_tool_calls_total",
    "Career Agent tool calls",
    ["tool_name", "source"],
)
agent_tool_failures = Counter(
    "agent_tool_failures_total",
    "Career Agent tool failures",
    ["tool_name", "failure_kind"],
)
agent_sse_connections_active = Gauge(
    "agent_sse_connections_active",
    "Active Career Agent SSE connections",
)
agent_sse_reconnects = Counter(
    "agent_sse_reconnects_total",
    "Career Agent SSE reconnect requests",
)
agent_lock_contention = Counter(
    "agent_lock_contention_total",
    "Career Agent run lock contention",
)
agent_event_publish_failures = Counter(
    "agent_event_publish_failures_total",
    "Career Agent event publication failures",
    ["event"],
)
