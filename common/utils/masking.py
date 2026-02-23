import re

def mask_phone(phone: str) -> str:
    """脱敏手机号: 138****1234"""
    if not phone:
        return ""
    if len(phone) < 7:
        return phone # Too short to mask safely
    return phone[:3] + "****" + phone[-4:]

def mask_email(email: str) -> str:
    """脱敏邮箱: a****@domain.com"""
    if not email or "@" not in email:
        return email
    user_part, domain = email.split("@", 1)
    if len(user_part) <= 1:
        return "*" + "@" + domain
    return user_part[0] + "****" + "@" + domain

def mask_name(name: str) -> str:
    """脱敏姓名: 张*"""
    if not name:
        return ""
    if len(name) <= 1:
        return name
    return name[0] + "*" * (len(name) - 1)

def mask_wechat(wechat: str) -> str:
    """脱敏微信号: w****"""
    if not wechat:
        return ""
    if len(wechat) <= 2:
        return wechat[0] + "*"
    return wechat[:1] + "****" + wechat[-1:]
