import aiohttp
import json
import time
import hashlib
import hmac
import base64
from typing import Optional
from core.logger import sys_logger as logger
from jobCollectionWebApi.config import settings


class SMSService:
    """短信服务（阿里云示例）"""
    
    def __init__(self):
        self.access_key_id = settings.SMS_ACCESS_KEY_ID
        self.access_key_secret = settings.SMS_ACCESS_KEY_SECRET
        self.sign_name = settings.SMS_SIGN_NAME
        self.template_code = settings.SMS_TEMPLATE_CODE
        self.endpoint = "dysmsapi.aliyuncs.com"
    
    def _get_signature(self, parameters: dict) -> str:
        """生成签名"""
        # 对参数进行排序
        sorted_params = sorted(parameters.items())
        
        # 构造待签名的字符串
        canonicalized_query_string = ""
        for (k, v) in sorted_params:
            canonicalized_query_string += '&' + self._percent_encode(k) + '=' + self._percent_encode(v)
        
        string_to_sign = 'GET&%2F&' + self._percent_encode(canonicalized_query_string[1:])
        
        # 计算签名
        key = self.access_key_secret + '&'
        signature = base64.b64encode(
            hmac.new(key.encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha1).digest()
        )
        
        return signature.decode('utf-8')
    
    def _percent_encode(self, encode_str: str) -> str:
        """URL 编码"""
        import urllib.parse
        return urllib.parse.quote(encode_str, safe='')
    
    async def send_verification_code(self, phone: str, code: str) -> bool:
        """发送验证码"""
        if not all([self.access_key_id, self.access_key_secret, self.sign_name, self.template_code]):
            logger.warning("SMS service not configured, using mock mode")
            # 在开发环境中模拟发送成功
            return True
        
        parameters = {
            'SignatureMethod': 'HMAC-SHA1',
            'SignatureNonce': str(int(time.time() * 1000)),
            'AccessKeyId': self.access_key_id,
            'SignatureVersion': '1.0',
            'Timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'Format': 'JSON',
            'Action': 'SendSms',
            'Version': '2017-05-25',
            'RegionId': 'cn-hangzhou',
            'PhoneNumbers': phone,
            'SignName': self.sign_name,
            'TemplateCode': self.template_code,
            'TemplateParam': json.dumps({'code': code})
        }
        
        # 生成签名
        signature = self._get_signature(parameters)
        parameters['Signature'] = signature
        
        # 发送请求
        url = f"http://{self.endpoint}/"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=parameters) as response:
                    result = await response.json()
                    
                    if result.get('Code') == 'OK':
                        logger.info(f"SMS sent successfully to {phone}")
                        return True
                    else:
                        logger.error(f"SMS send failed: {result}")
                        return False
        except Exception as e:
            logger.error(f"SMS service error: {e}")
            return False

# 全局短信服务实例
sms_service = SMSService()
