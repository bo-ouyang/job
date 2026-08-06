import hashlib

import pytest


def test_canonical_url_removes_tracking_and_sorts_position_codes():
    from jobCollection.jobCollection.boss.urls import canonicalize_boss_task_url

    raw_url = (
        "https://www.zhipin.com/web/geek/jobs?"
        "position=300403,300401,210502,210108,210101,300402,300309,210115,300406"
        "&experience=102&ka=major_filter_%E5%85%BD%E5%8C%BB%E5%AD%A6_click"
    )

    assert canonicalize_boss_task_url(raw_url) == (
        "https://www.zhipin.com/web/geek/jobs?experience=102&"
        "position=210101,210108,210115,210502,300309,300401,300402,300403,300406"
    )


def test_canonical_url_preserves_source_experience_and_stably_orders_parameters():
    from jobCollection.jobCollection.boss.urls import canonicalize_boss_task_url

    assert canonicalize_boss_task_url(
        "https://www.zhipin.com/web/geek/jobs?position=300403,210101,300403"
        "&city=101010100&experience=108&ka=ignored"
    ) == (
        "https://www.zhipin.com/web/geek/jobs?city=101010100&experience=108&"
        "position=210101,300403"
    )


def test_canonical_url_collects_repeated_position_parameters():
    from jobCollection.jobCollection.boss.urls import canonicalize_boss_task_url

    assert canonicalize_boss_task_url(
        "https://www.zhipin.com/web/geek/jobs?position=300403&position=210101,300403"
    ).endswith("?position=210101,300403")


@pytest.mark.parametrize("raw_url", ["", "   ", "/web/geek/jobs?position=1"])
def test_canonical_url_rejects_empty_or_non_absolute_urls(raw_url):
    from jobCollection.jobCollection.boss.urls import canonicalize_boss_task_url

    with pytest.raises(ValueError):
        canonicalize_boss_task_url(raw_url)


def test_canonical_identity_hash_is_stable_after_tracking_is_removed():
    from jobCollection.jobCollection.boss.urls import canonicalize_boss_task_url

    first = canonicalize_boss_task_url(
        "https://www.zhipin.com/web/geek/jobs?position=2,1&experience=105&ka=first"
    )
    second = canonicalize_boss_task_url(
        "https://www.zhipin.com/web/geek/jobs?ka=second&experience=105&position=1,2"
    )

    assert first == second
    assert hashlib.sha256(first.encode("utf-8")).hexdigest() == hashlib.sha256(
        second.encode("utf-8")
    ).hexdigest()
