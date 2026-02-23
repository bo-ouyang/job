from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, BigInteger
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from common.databases.models.base import Base
import enum
from common.utils.snowflake import generate_id

class TransactionType(str, enum.Enum):
    DEPOSIT = "deposit"      # 充值
    CONSUME = "consume"      # 消费
    REFUND = "refund"        # 退款
    WITHDRAW = "withdraw"    # 提现

class WalletStatus(str, enum.Enum):
    ACTIVE = "active"
    FROZEN = "frozen"

class UserWallet(Base):
    __tablename__ = "user_wallets"

    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    
    balance = Column(Float, default=0.0, nullable=False, comment="可用余额")
    frozen_balance = Column(Float, default=0.0, nullable=False, comment="冻结金额")
    
    status = Column(Enum(WalletStatus), default=WalletStatus.ACTIVE)
    password_hash = Column(String(128), nullable=True, comment="支付密码")
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="wallet")
    transactions = relationship("WalletTransaction", back_populates="wallet", cascade="all, delete-orphan")

class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    wallet_id = Column(BigInteger, ForeignKey("user_wallets.id"), nullable=False)
    
    amount = Column(Float, nullable=False, comment="变动金额 (+/-)")
    balance_after = Column(Float, nullable=False, comment="变动后余额")
    
    transaction_type = Column(Enum(TransactionType), nullable=False)
    related_order_no = Column(String(64), index=True, nullable=True, comment="关联订单号")
    description = Column(String(255), nullable=True)
    
    created_at = Column(DateTime, default=func.now())

    # Relationships
    wallet = relationship("UserWallet", back_populates="transactions")
