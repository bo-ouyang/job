from dataclasses import dataclass
import time
from typing import Dict, List

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.RedisManager import redis_manager
from common.databases.models.product import Product
from config import settings
from core.logger import sys_logger as logger
from crud import product as crud_product
from crud import wallet as crud_wallet


@dataclass(frozen=True)
class AIFeaturePolicy:
    feature_key: str
    product_code: str
    default_price: float
    requests_per_minute: int
    description: str


class AIAccessService:
    def __init__(self) -> None:
        self._policy_map: Dict[str, AIFeaturePolicy] = {
            "career_advice": AIFeaturePolicy(
                feature_key="career_advice",
                product_code="ai_career_advice",
                default_price=settings.AI_PRICE_CAREER_ADVICE,
                requests_per_minute=settings.AI_RATE_LIMIT_CAREER_ADVICE_PER_MINUTE,
                description="AI career advice",
            ),
            "career_compass": AIFeaturePolicy(
                feature_key="career_compass",
                product_code="ai_career_compass",
                default_price=settings.AI_PRICE_CAREER_COMPASS,
                requests_per_minute=settings.AI_RATE_LIMIT_CAREER_COMPASS_PER_MINUTE,
                description="AI career compass",
            ),
            "ai_search": AIFeaturePolicy(
                feature_key="ai_search",
                product_code="ai_search_intent",
                default_price=settings.AI_PRICE_AI_SEARCH,
                requests_per_minute=settings.AI_RATE_LIMIT_AI_SEARCH_PER_MINUTE,
                description="AI intent search",
            ),
            "resume_parse": AIFeaturePolicy(
                feature_key="resume_parse",
                product_code="ai_resume_parse",
                default_price=settings.AI_PRICE_RESUME_PARSE,
                requests_per_minute=settings.AI_RATE_LIMIT_RESUME_PARSE_PER_MINUTE,
                description="AI resume parse",
            ),
        }

    def list_pricing_templates(self) -> List[dict]:
        templates: List[dict] = []
        for policy in self._policy_map.values():
            templates.append(
                {
                    "name": policy.description,
                    "code": policy.product_code,
                    "category": "ai_service",
                    "description": f"Auto-billing for {policy.feature_key}",
                    "price": max(float(policy.default_price), 0.0),
                    "original_price": max(float(policy.default_price), 0.0),
                    "is_active": True,
                }
            )
        return templates

    async def ensure_pricing_products(self, db: AsyncSession) -> int:
        created_count = 0
        for product_data in self.list_pricing_templates():
            existing = await crud_product.product.get_by_code(db, product_data["code"])
            if existing:
                continue
            db.add(Product(**product_data))
            created_count += 1

        if created_count > 0:
            await db.commit()
        return created_count

    def _get_policy(self, feature_key: str) -> AIFeaturePolicy:
        policy = self._policy_map.get(feature_key)
        if not policy:
            raise HTTPException(status_code=500, detail=f"Unknown AI feature: {feature_key}")
        return policy

    async def _enforce_rate_limit(self, user_id: int, policy: AIFeaturePolicy) -> None:
        if not settings.AI_RATE_LIMIT_ENABLED:
            return

        current_minute = int(time.time()) // 60
        limit_key = f"rate_limit:ai:user:{user_id}:{policy.feature_key}:{current_minute}"
        try:
            current_count = await redis_manager.increment_counter(limit_key)
            if current_count == 1:
                await redis_manager.redis_client.expire(redis_manager.make_key(limit_key), 70)

            if current_count > policy.requests_per_minute:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        f"Rate limit exceeded for {policy.feature_key}. "
                        f"Max {policy.requests_per_minute} requests per minute."
                    ),
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"AI rate limiter degraded for {policy.feature_key}: {exc}")

    async def _resolve_price(self, db: AsyncSession, policy: AIFeaturePolicy) -> float:
        if not settings.AI_BILLING_ENABLED:
            return 0.0

        product = await crud_product.product.get_by_code(db, policy.product_code)
        if product and product.is_active:
            return max(float(product.price), 0.0)

        if settings.AI_BILLING_REQUIRE_PRODUCT:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Billing product is not configured: {policy.product_code}",
            )

        return max(float(policy.default_price), 0.0)

    async def ensure_access(self, db: AsyncSession, user_id: int, feature_key: str) -> float:
        policy = self._get_policy(feature_key)
        await self._enforce_rate_limit(user_id=user_id, policy=policy)

        price = await self._resolve_price(db=db, policy=policy)
        if price <= 0:
            return 0.0

        wallet = await crud_wallet.wallet.get_by_user(db, user_id=user_id)
        balance = float(wallet.balance) if wallet else 0.0
        if balance < price:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Insufficient wallet balance for {policy.description}. "
                    f"Required: {price:.2f}, current: {balance:.2f}"
                ),
            )
        return price

    async def charge_usage(
        self,
        db: AsyncSession,
        user_id: int,
        feature_key: str,
        amount: float,
        detail_suffix: str = "",
    ) -> None:
        if amount <= 0:
            return

        policy = self._get_policy(feature_key)
        description = f"{policy.description} usage"
        if detail_suffix:
            description = f"{description} ({detail_suffix})"

        success = await crud_wallet.wallet.consume_balance(
            db,
            user_id=user_id,
            amount=amount,
            description=description,
        )
        if not success:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Wallet charge failed for {policy.description}",
            )
        await db.commit()


ai_access_service = AIAccessService()
