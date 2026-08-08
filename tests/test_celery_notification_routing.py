from jobCollectionWebApi.core.celery_app import celery_app


def test_notification_tasks_are_routed_to_the_realtime_worker():
    routes = celery_app.conf.task_routes

    assert routes["tasks.notification_tasks.*"]["queue"] == "realtime"
