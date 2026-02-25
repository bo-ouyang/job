import aiohttp
import json
from typing import Optional, Dict, Any
from core.logger import sys_logger as logger
from jobCollectionWebApi.config import settings


class WeChatService:
    """微信登录服务"""
    
    def __init__(self):
        self.app_id = settings.WECHAT_APP_ID
        self.app_secret = settings.WECHAT_APP_SECRET
        self.redirect_uri = settings.WECHAT_REDIRECT_URI
    
    async def get_access_token(self, code: str) -> Optional[Dict[str, Any]]:
        """获取微信访问令牌"""
        url = "https://api.weixin.qq.com/sns/oauth2/access_token"
        params = {
            "appid": self.app_id,
            "secret": self.app_secret,
            "code": code,
            "grant_type": "authorization_code"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    data = await response.json()
                    
                    if "errcode" in data:
                        logger.error(f"WeChat API error: {data}")
                        return None
                    
                    return data
        except Exception as e:
            logger.error(f"WeChat API request failed: {e}")
            return None
    
    async def get_user_info(self, access_token: str, openid: str) -> Optional[Dict[str, Any]]:
        """获取微信用户信息"""
        url = "https://api.weixin.qq.com/sns/userinfo"
        params = {
            "access_token": access_token,
            "openid": openid,
            "lang": "zh_CN"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    data = await response.json()
                    
                    if "errcode" in data:
                        logger.error(f"WeChat user info error: {data}")
                        return None
                    
                    return data
        except Exception as e:
            logger.error(f"WeChat user info request failed: {e}")
            return None
    
    async def verify_access_token(self, access_token: str, openid: str) -> bool:
        """验证微信访问令牌"""
        url = "https://api.weixin.qq.com/sns/auth"
        params = {
            "access_token": access_token,
            "openid": openid
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    data = await response.json()
                    return data.get("errcode") == 0
        except Exception as e:
            logger.error(f"WeChat token verification failed: {e}")
            return False
    
    async def login_with_code(self, code: str) -> Optional[Dict[str, Any]]:
        """使用 code 进行微信登录"""
        # 获取访问令牌
        token_data = await self.get_access_token(code)
        if not token_data:
            return None
        
        access_token = token_data.get("access_token")
        openid = token_data.get("openid")
        
        if not access_token or not openid:
            return None
        
        # 验证令牌
        is_valid = await self.verify_access_token(access_token, openid)
        if not is_valid:
            return None
        
        # 获取用户信息
        user_info = await self.get_user_info(access_token, openid)
        if not user_info:
            return None
        
        return {
            "openid": openid,
            "unionid": user_info.get("unionid"),
            "nickname": user_info.get("nickname"),
            "avatar": user_info.get("headimgurl"),
            "sex": user_info.get("sex"),
            "province": user_info.get("province"),
            "city": user_info.get("city"),
            "country": user_info.get("country")
        }

# 全局微信服务实例
wechat_service = WeChatService()
