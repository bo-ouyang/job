"""Metric ownership shared by the crawler workflow, Agent, and control plane."""


# These counters are derived from durable boss_crawl_run_job rows by Progress.
# Agent process snapshots are observational and must never author these facts.
PROGRESS_FACT_METRICS = frozenset(
    {
        "listSeenCount",
        "jobsDiscovered",
        "uniqueCount",
        "duplicateCount",
        "detailSuccessCount",
        "detailFailedCount",
        "itemsScraped",
        "errors",
        "retries",
    }
)
