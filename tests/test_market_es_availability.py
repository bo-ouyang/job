import sys
from pathlib import Path

from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch import ApiError, ConnectionTimeout


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from services.market.es_availability import classify_es_fallback


def _api_error(status_code: int) -> ApiError:
    return ApiError(
        "Elasticsearch response failed",
        ApiResponseMeta(
            status_code,
            "1.1",
            HttpHeaders(),
            0.0,
            NodeConfig("http", "localhost", 9200),
        ),
        {},
    )


def test_es_fallback_classifier_accepts_transport_and_retryable_http_errors():
    assert classify_es_fallback(ConnectionTimeout("timed out")).warning_code("market.stats") == (
        "market.stats.es_fallback:ConnectionTimeout"
    )
    assert classify_es_fallback(_api_error(429)).warning_code("market.stats") == (
        "market.stats.es_fallback:ApiError:429"
    )
    assert classify_es_fallback(_api_error(503)).warning_code("market.stats") == (
        "market.stats.es_fallback:ApiError:503"
    )


def test_es_fallback_classifier_rejects_non_retryable_http_errors():
    assert classify_es_fallback(_api_error(400)) is None
