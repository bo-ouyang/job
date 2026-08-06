"""Environment-backed proxy configuration and Chrome extension generation."""

import json
import os
import random
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Mapping, Optional
from urllib.parse import quote, unquote, urlsplit

import httpx


def load_proxy_pool_config(
    environ: Optional[Mapping[str, str]] = None,
) -> Dict[str, object]:
    """Read proxy-pool settings without embedding credentials in source code."""
    values = os.environ if environ is None else environ
    return {
        "api_url": values.get("BOSS_PROXY_API_URL", ""),
        "username": values.get("BOSS_PROXY_USERNAME", ""),
        "password": values.get("BOSS_PROXY_PASSWORD", ""),
        "min_pool_size": int(values.get("BOSS_PROXY_MIN_POOL_SIZE", "1")),
    }


class ProxyPoolManager:
    """Small environment-configured proxy pool used by the retained spiders."""

    def __init__(self, config: Mapping[str, object]):
        self.api_url = str(config.get("api_url") or "")
        self.username = str(config.get("username") or "")
        self.password = str(config.get("password") or "")
        self.min_pool_size = max(1, int(config.get("min_pool_size") or 1))
        self.proxy_pool: List[str] = []
        self.last_fetch_time = 0.0
        self.fetch_cooldown = 5.0

    def fetch_proxies(self) -> bool:
        if not self.api_url or time.time() - self.last_fetch_time < self.fetch_cooldown:
            return False
        try:
            response = httpx.get(self.api_url, timeout=10)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return False
            if payload.get("code") not in (None, 0):
                return False
            data = payload.get("data")
            if not isinstance(data, dict):
                return False
            proxy_values = data.get("proxy_list", [])
            if not isinstance(proxy_values, list):
                return False
            for value in proxy_values:
                address = str(value).strip()
                if not address:
                    continue
                if self.username and self.password:
                    proxy_url = "http://{}:{}@{}".format(
                        quote(self.username, safe=""),
                        quote(self.password, safe=""),
                        address,
                    )
                else:
                    proxy_url = address if "://" in address else "http://{}".format(address)
                if proxy_url not in self.proxy_pool:
                    self.proxy_pool.append(proxy_url)
            self.last_fetch_time = time.time()
            return bool(proxy_values)
        except (httpx.HTTPError, TypeError, ValueError):
            return False

    def get_proxy(self) -> Optional[str]:
        if len(self.proxy_pool) < self.min_pool_size:
            self.fetch_proxies()
        return random.choice(self.proxy_pool) if self.proxy_pool else None

    def remove_proxy(self, proxy_url: Optional[str]) -> None:
        if proxy_url in self.proxy_pool:
            self.proxy_pool.remove(proxy_url)


proxy_manager = ProxyPoolManager(load_proxy_pool_config())


def parse_authenticated_proxy_url(proxy_url: str) -> Dict[str, object]:
    """Parse an authenticated HTTP proxy URL into extension-ready values."""
    parsed = urlsplit(proxy_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("authenticated proxy must use http or https")
    if not parsed.hostname or parsed.port is None:
        raise ValueError("authenticated proxy must include host and port")
    if parsed.username is None or parsed.password is None:
        raise ValueError("authenticated proxy must include username and password")

    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "username": unquote(parsed.username),
        "password": unquote(parsed.password),
    }


def create_proxy_auth_extension(
    proxy_url: str, output_root: os.PathLike, namespace: str
) -> str:
    """Create a Chrome proxy-auth extension using only explicit runtime inputs."""
    proxy = parse_authenticated_proxy_url(proxy_url)
    safe_namespace = re.sub(r"[^A-Za-z0-9_.-]+", "_", namespace).strip("_") or "default"
    extension_root = Path(output_root) / "proxy_extensions"
    extension_root.mkdir(parents=True, exist_ok=True)
    extension_path = Path(
        tempfile.mkdtemp(prefix=f"{safe_namespace}_", dir=str(extension_root))
    )

    manifest = {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "BOSS Proxy %s" % namespace,
        "permissions": [
            "proxy",
            "tabs",
            "unlimitedStorage",
            "storage",
            "<all_urls>",
            "webRequest",
            "webRequestBlocking",
        ],
        "background": {"scripts": ["background.js"]},
        "minimum_chrome_version": "22.0.0",
    }
    background = """var config = {{
    mode: "fixed_servers",
    rules: {{ singleProxy: {{ scheme: {scheme}, host: {host}, port: parseInt({port}) }}, bypassList: ["localhost"] }}
}};
chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});
function callbackFn(details) {{
    return {{ authCredentials: {{ username: {username}, password: {password} }} }};
}}
chrome.webRequest.onAuthRequired.addListener(callbackFn, {{urls: ["<all_urls>"]}}, ["blocking"]);
""".format(
        scheme=json.dumps(proxy["scheme"]),
        host=json.dumps(proxy["host"]),
        port=json.dumps(proxy["port"]),
        username=json.dumps(proxy["username"]),
        password=json.dumps(proxy["password"]),
    )

    (extension_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (extension_path / "background.js").write_text(background, encoding="utf-8")
    return str(extension_path)


def cleanup_proxy_auth_extension(extension_path: Optional[os.PathLike]) -> None:
    """Best-effort removal of a generated extension containing proxy credentials."""
    if extension_path:
        shutil.rmtree(Path(extension_path), ignore_errors=True)
