from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.sql import func
from .base import Base

class Proxy(Base):
    __tablename__ = 'proxies'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(String(50), nullable=False)
    port = Column(Integer, nullable=False)
    protocol = Column(String(10), default='http') # http, https, socks5
    source = Column(String(50), nullable=False, index=True) # e.g. "manual", "vendor_a"
    
    score = Column(Integer, default=100)
    latency = Column(Float, default=0.0) # ms
    is_active = Column(Boolean, default=True, index=True)
    
    fail_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    
    last_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Proxy(ip={self.ip}, port={self.port}, score={self.score})>"
