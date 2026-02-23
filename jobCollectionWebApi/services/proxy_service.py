import json
import asyncio
import logging
import aiohttp
import time
from sqlalchemy import select, update, insert
from sqlalchemy.ext.asyncio import AsyncSession
from common.databases.PostgresManager import db_manager
from common.databases.models.proxy import Proxy
from jobCollectionWebApi.core.celery_app import celery_app
from jobCollectionWebApi.config import settings
from redis.asyncio import Redis

# Redis Keys
PROXY_POOL_KEY = "proxy_pool" # Set of "ip:port"
PROXY_SCORE_KEY = "proxy_score" # Sorted Set: "ip:port" -> score
PROXY_INFO_KEY = "proxy_info" # Hash: "ip:port" -> json({protocol, source, latency, fail_count...})

logger = logging.getLogger(__name__)

class ProxyService:
    def __init__(self, redis_url=None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis = None

    async def get_redis(self):
        if not self._redis:
            self._redis = Redis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    async def fetch_proxies_from_source(self):
        """
        Fetch from external sources
        """
        # 1. Mock/Local
        # proxies = [{"ip": "127.0.0.1", "port": 8888, "protocol": "http", "source": "local_mock"}]
        # await self.save_proxies(proxies)
        
        # 2. 89ip
        await self.fetch_89ip_proxies()

    async def fetch_from_url(self, url: str):
        """
        Fetch proxies from a generic URL using regex to find IP:Port patterns
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        import re
                        # 1. Find all IPs
                        ip_matches = list(re.finditer(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', text))
                        logger.info(f"Fetched {len(ip_matches)} IPs from URL: {url}")
                        
                        proxies = []
                        for match in ip_matches:
                            ip = match.group(1)
                            start, end = match.span()
                            
                            # Look for port in the next 100 chars
                            # This handles "IP:Port" and "<td>IP</td>...<td>Port</td>"
                            context = text[end:end+100]
                            port_match = re.search(r'(\d{2,5})', context)
                            
                            if port_match:
                                port = int(port_match.group(1))
                                if 1 <= port <= 65535:
                                    # Optional: Look for speed (float) checks
                                    # Context: Port end + 200 chars
                                    port_end = port_match.end()
                                    remaining = context[port_end:]
                                    
                                    # Heuristic: Find first float number. 
                                    # Only filter if we find a small float (likely speed) or really clearly a speed.
                                    # To avoid false positives (like dates 2023.01), we can check if value is small?
                                    # Or just strict: if we find a float and it is >= 1, skip?
                                    # Use a simple regex that matches typical speed (0.xxx or single digits.xxx)
                                    speed_match = re.search(r'(\d+\.\d+)', remaining)
                                    should_add = True
                                    
                                    if speed_match:
                                        try:
                                            speed_val = float(speed_match.group(1))
                                            # If it looks like a speed (e.g. < 60s)
                                            # User criteria: < 1s
                                            # But if it matches a date year like 2025.01, it is > 1.
                                            # Logic: If found value is "speed-like" (e.g. appear in table), filter it.
                                            # We assume if we find a float near the port, it's likely speed/latency.
                                            if speed_val >= 1.0:
                                                should_add = False
                                                # logger.debug(f"Skipping {ip}:{port} due to speed {speed_val}")
                                        except:
                                            pass

                                    if should_add:
                                        proxies.append({
                                            "ip": ip,
                                            "port": port,
                                            "protocol": "http", # Default assumption
                                            "source": "custom_url"
                                        })
                        
                        if proxies:
                            await self.save_proxies(proxies)
                        return len(proxies)
        except Exception as e:
            logger.error(f"Error fetching from {url}: {e}")
            return 0

    async def fetch_89ip_proxies(self):
        url = "http://www.89ip.cn/tqdl.html?api=1&num=100"
        await self.fetch_from_url(url)


    async def save_proxies(self, proxy_list):
        """
        Save new proxies to Redis (and DB if new)
        """
        redis = await self.get_redis()
        
        async with (await db_manager.get_session()) as session:
            for p in proxy_list:
                proxy_str = f"{p['ip']}:{p['port']}"
                
                # 1. Update Redis
                if not await redis.sismember(PROXY_POOL_KEY, proxy_str):
                    await redis.sadd(PROXY_POOL_KEY, proxy_str)
                    await redis.zadd(PROXY_SCORE_KEY, {proxy_str: 100}) # Initial score
                    await redis.hset(PROXY_INFO_KEY, proxy_str, json.dumps({
                        "protocol": p['protocol'],
                        "source": p['source'],
                        "latency": 0,
                        "fail_count": 0,
                        "is_active": True
                    }))
                    
                    # 2. Update DB (Insert if not exists)
                    # We can use insert().on_conflict_do_nothing()
                    stmt = select(Proxy).where(Proxy.ip == p['ip'], Proxy.port == p['port'])
                    result = await session.execute(stmt)
                    if not result.scalar_one_or_none():
                        new_proxy = Proxy(
                            ip=p['ip'],
                            port=p['port'],
                            protocol=p['protocol'],
                            source=p['source'],
                            score=100,
                            is_active=True
                        )
                        session.add(new_proxy)
            
            await session.commit()

    async def check_proxies(self):
        """
        Iterate all proxies in Redis and check availability.
        Updates Score and Status in Redis ONLY.
        """
        redis = await self.get_redis()
        proxies = await redis.smembers(PROXY_POOL_KEY)
        
        if not proxies:
            logger.info("No proxies to check.")
            return

        logger.info(f"Checking {len(proxies)} proxies...")
        
        tasks = []
        for proxy_str in proxies:
            tasks.append(self.verify_proxy(proxy_str))
        
        results = await asyncio.gather(*tasks)
        logger.info(f"Proxy check complete. Success: {sum(r['success'] for r in results)}")

    async def verify_proxy(self, proxy_str):
        redis = await self.get_redis()
        info_json = await redis.hget(PROXY_INFO_KEY, proxy_str)
        info = json.loads(info_json) if info_json else {}
        
        protocol = info.get('protocol', 'http')
        url = "https://www.baidu.com/" # Target for testing
        proxy_url = f"{protocol}://{proxy_str}"
        
        start_time = time.time()
        success = False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, proxy=proxy_url, timeout=5) as resp:
                    if resp.status == 200:
                        success = True
        except Exception as e:
            logger.warning(f"Proxy {proxy_str} check failed: {e}")
            pass
        
        latency = (time.time() - start_time) * 1000 # ms
        
        # Update Score in Redis
        current_score = await redis.zscore(PROXY_SCORE_KEY, proxy_str)
        current_score = int(current_score) if current_score else 50
        
        if success:
            new_score = min(100, current_score + 1)
            info['fail_count'] = 0
            info['latency'] = latency
        else:
            new_score = max(0, current_score - 10)
            info['fail_count'] = info.get('fail_count', 0) + 1
            info['latency'] = -1
        
        # Disable if score too low
        if new_score < 10:
            info['is_active'] = False
            # Optional: Remove from POOL_KEY to stop serving it, but keep in SCORE for retry?
            # For now, we just mark as inactive in info.
        else:
             info['is_active'] = True

        await redis.zadd(PROXY_SCORE_KEY, {proxy_str: new_score})
        await redis.hset(PROXY_INFO_KEY, proxy_str, json.dumps(info))
        
        return {"proxy": proxy_str, "success": success, "score": new_score}

    async def get_proxy(self):
        """
        Get a random high scoring proxy
        """
        redis = await self.get_redis()
        # Get proxies with score >= 80
        proxies = await redis.zrangebyscore(PROXY_SCORE_KEY, 80, 100)
        if not proxies:
            return None
            
        import random
        proxy_str = random.choice(proxies)
        info_json = await redis.hget(PROXY_INFO_KEY, proxy_str)
        info = json.loads(info_json) if info_json else {}
        
        return {
            "ip": proxy_str.split(':')[0],
            "port": int(proxy_str.split(':')[1]),
            "protocol": info.get('protocol', 'http'),
            "auth": None # Add auth support if needed
        }

    async def sync_to_db(self):
        """
        Sync Redis state to Postgres
        """
        logger.info("Syncing proxies from Redis to DB...")
        redis = await self.get_redis()
        proxies = await redis.smembers(PROXY_POOL_KEY)
        
        count = 0
        async with (await db_manager.get_session()) as session:
            for proxy_str in proxies:
                score = await redis.zscore(PROXY_SCORE_KEY, proxy_str)
                info_json = await redis.hget(PROXY_INFO_KEY, proxy_str)
                if not info_json: continue
                
                info = json.loads(info_json)
                ip, port = proxy_str.split(':')
                
                stmt = update(Proxy).where(Proxy.ip == ip, Proxy.port == int(port)).values(
                    score=int(score) if score else 0,
                    latency=info.get('latency', 0),
                    is_active=info.get('is_active', True),
                    fail_count=info.get('fail_count', 0),
                    # updated_at will auto update
                )
                await session.execute(stmt)
                count += 1
            
            await session.commit()
        logger.info(f"Synced {count} proxies to DB.")

proxy_service = ProxyService()
