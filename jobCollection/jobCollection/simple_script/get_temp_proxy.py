#!/usr/bin/env Python
# -*- coding: utf-8 -*-

"""
使用requests请求代理服务器
请求http和https网页均适用
"""

import random
import asyncio

import httpx
import requests

page_url = "http://icanhazip.com/"  # 要访问的目标网页

# API接口，返回格式为json
api_url = "https://dps.kdlapi.com/api/getdps/?secret_id=o8ca6frqsdj5jf4lr1bf&signature=56ok0quipufcj1tb15s0f4dwh1u66whi&num=10&format=json&sep=1"  # API接口

# API接口返回的proxy_list
proxy_list = requests.get(api_url).json().get('data').get('proxy_list')

# 用户名密码认证(私密代理/独享代理)
username = "d3248275594"
password = "xc1zag9a"


async def fetch(url):
    async with httpx.AsyncClient(proxy = f"http://{username}:{password}@{random.choice(proxy_list)}",timeout=10) as client:
        resp = await client.get(url)
        print(f"status_code: {resp.status_code}, content: {resp.content}")


async def run():
    # 异步发出5次请求
    tasks = [fetch(page_url) for _ in range(5)]
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(run())