from jobCollectionWebApi.core.celery_app import celery_app
from jobCollectionWebApi.services.proxy_service import proxy_service
import asyncio

@celery_app.task(name="tasks.check_proxies")
def check_proxies_task():
    """
    Periodic task to check proxy availability (Redis only)
    """
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    loop.run_until_complete(proxy_service.check_proxies())

@celery_app.task(name="tasks.fetch_proxies")
def fetch_proxies_task():
    """
    Periodic task to fetch new proxies from sources
    """
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    loop.run_until_complete(proxy_service.fetch_proxies_from_source())

@celery_app.task(name="tasks.fetch_custom_proxies")
def fetch_custom_proxies_task(url: str):
    """
    Task to fetch proxies from a user provided URL
    """
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    loop.run_until_complete(proxy_service.fetch_from_url(url))

@celery_app.task(name="tasks.sync_proxies")
def sync_proxies_to_db_task():
    """
    Periodic task to sync Redis state to DB
    """
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    loop.run_until_complete(proxy_service.sync_to_db())
