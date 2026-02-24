import logging
import random
import redis
import json
from scrapy import signals

logger = logging.getLogger(__name__)

class RandomProxyMiddleware:
    def __init__(self, redis_url):
        self.redis_url = redis_url
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.proxy_score_key = "proxy_score" # matches ProxyService
        self.proxy_info_key = "proxy_info"

    @classmethod
    def from_crawler(cls, crawler):
        # We can get settings from crawler.settings
        # Assuming REDIS_URL is in settings (it might not be, so fallback)
        # Or we can put it in custom settings
        redis_url = crawler.settings.get('REDIS_URL', 'redis://localhost:6379/0')
        s = cls(redis_url)
        crawler.signals.connect(s.spider_closed, signal=signals.spider_closed)
        return s

    def process_request(self, request, spider):
        # Don't overwrite if proxy is already set
        if request.meta.get('proxy'):
            return

        # Fetch high scoring proxies (e.g. > 60)
        # Using synchronous redis for simplicity in middleware process_request (Scrapy is sync by default unless using async reactor but middleware is often sync)
        # Actually scrapy is async but middleware runs in main reactor thread usually?
        # redis-py is sync, redis.asyncio is async.
        # Scrapy middlewares can be async in recent versions, but sync is safer for simple logic.
        
        try:
            # Randomly pick from top range
            # zrangebyscore returns list
            proxies = self.redis.zrangebyscore(self.proxy_score_key, 60, 100)
            
            if proxies:
                proxy = random.choice(proxies)
                
                # Get protocol
                info_json = self.redis.hget(self.proxy_info_key, proxy)
                protocol = "http"
                if info_json:
                    try:
                        info = json.loads(info_json)
                        protocol = info.get('protocol', 'http')
                    except:
                        pass
                
                proxy_url = f"{protocol}://{proxy}"
                request.meta['proxy'] = proxy_url
                request.meta['download_timeout'] = 10 # Short timeout for proxies
                logger.debug(f"Using proxy: {proxy_url}")
            else:
                logger.warning("No usable proxies found in Redis!")
        except Exception as e:
            logger.error(f"Error setting proxy: {e}")

    def process_exception(self, request, exception, spider):
        # Handle connection errors
        proxy = request.meta.get('proxy')
        if proxy:
            logger.warning(f"Proxy {proxy} failed: {exception}")
            self._punish_proxy(proxy)
            # Retry request without this proxy or with new one?
            # Scrapy RetryMiddleware will handle retry if we return Request, but let's just let it bubble or return None
            # If we return None, exception is propagated.
            # Ideally retry with a different proxy.
            
            # Remove proxy from meta to avoid reuse in retry
            del request.meta['proxy'] 
            return request.replace(dont_filter=True) # Retry
            
    def _punish_proxy(self, proxy_url):
        # proxy_url is "http://1.2.3.4:80"
        # We need "1.2.3.4:80"
        try:
            if "://" in proxy_url:
                proxy_str = proxy_url.split("://")[1]
            else:
                proxy_str = proxy_url
                
            # Decrease score
            self.redis.zincrby(self.proxy_score_key, -10, proxy_str)
        except Exception as e:
            logger.error(f"Error punishing proxy: {e}")

    def spider_closed(self, spider):
        self.redis.close()
