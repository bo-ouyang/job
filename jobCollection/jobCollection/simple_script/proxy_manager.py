import httpx
import random
import time
from urllib.parse import urlparse

class KDLProxyManager:
    def __init__(self, api_url, username, password, min_pool_size=1):
        self.api_url = api_url
        self.username = username
        self.password = password
        self.min_pool_size = min_pool_size
        self.proxy_pool = []
        self.last_fetch_time = 0.0
        self.fetch_cooldown = 5  # Seconds between API calls to prevent rate limiting
        
    def fetch_proxies(self):
        """Fetch new proxies from KDL API"""
        now = time.time()
        if now - self.last_fetch_time < self.fetch_cooldown:
            return False
            
        print("[ProxyManager] Fetching new proxies from KDL API...")
        try:
            # Synchronous fetch for simplicity in DP controller
            response = httpx.get(self.api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 0:
                    new_proxies = data.get('data', {}).get('proxy_list', [])
                    if new_proxies:
                        for p in new_proxies:
                            # Format: http://user:pass@ip:port
                            formatted_proxy = f"http://{self.username}:{self.password}@{p}"
                            if formatted_proxy not in self.proxy_pool:
                                self.proxy_pool.append(formatted_proxy)
                        print(f"[ProxyManager] Successfully added {len(new_proxies)} proxies. Total in pool: {len(self.proxy_pool)}")
                        self.last_fetch_time = time.time()
                        return True
                else:
                    print(f"[ProxyManager] API Error: {data.get('msg')}")
            else:
                print(f"[ProxyManager] HTTP Error: {response.status_code}")
        except Exception as e:
            print(f"[ProxyManager] Exception fetching proxies: {e}")
        return False

    def get_proxy(self):
        """Get a random proxy from the pool, fetch more if needed"""
        if len(self.proxy_pool) < self.min_pool_size:
            self.fetch_proxies()
            
        if not self.proxy_pool:
            # Fallback if API fails repeatedly
            print("[ProxyManager] WARNING: Proxy pool is empty! Using direct connection or waiting.")
            return None
            
        return random.choice(self.proxy_pool)
        
    def remove_proxy(self, proxy):
        """Remove a dead/blocked proxy from the pool"""
        if proxy in self.proxy_pool:
            self.proxy_pool.remove(proxy)
            print(f"[ProxyManager] Removed bad proxy. Remaining in pool: {len(self.proxy_pool)}")

# Global instance based on user's credentials
# It's better to read from .env in a real scenario, but setting here directly for the specific script as requested
KDL_API_URL = "https://dps.kdlapi.com/api/getdps/?secret_id=ox2wp9u6sukkz7ll41ss&signature=fy5rg6k9wxtykpugqg65gwn58f4r8g3s&num=3&format=json&sep=1"
KDL_USER = "d2006816196"
KDL_PASS = "xc1zag9a"

proxy_manager = KDLProxyManager(KDL_API_URL, KDL_USER, KDL_PASS)
