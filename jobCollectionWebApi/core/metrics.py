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
