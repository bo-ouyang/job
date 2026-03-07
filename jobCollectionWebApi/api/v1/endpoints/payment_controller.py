import json
import uuid
from datetime import datetime
from typing import Any, Optional

from alipay import AliPay
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from wechatpayv3 import WeChatPay, WeChatPayType

from common.databases.RedisManager import redis_manager
from common.databases.models.payment import PaymentMethod, PaymentOrder, PaymentStatus
from common.databases.models.wallet import TransactionType
from config import settings
from core.exceptions import AppException, ExternalServiceException, PermissionDeniedException
from core.logger import sys_logger as logger
from core.status_code import StatusCode
from crud import payment as crud_payment
from crud import product as crud_product
from crud import wallet as crud_wallet
from crud.message import message as crud_message
from dependencies import get_current_admin_user, get_current_user, get_db
from schemas.message_schema import MessageCreate, MessageType
from schemas.payment_schema import (
    PaymentOrderCreate,
    PaymentOrderPage,
    PaymentOrderResponse,
    PaymentOrderSchema,
)

router = APIRouter()

alipay_client: Optional[AliPay] = None
wechat_client: Optional[WeChatPay] = None


def _build_provider_notify_url(provider: str) -> str:
    base = (settings.PAYMENT_NOTIFY_BASE_URL or "").strip().rstrip("/")
    if not base:
        return f"/{provider}"
    suffix = f"/{provider}"
    if base.endswith(suffix):
        return base
    return f"{base}{suffix}"


def _init_alipay_client() -> Optional[AliPay]:
    if not settings.ALIPAY_APP_ID:
        return None
    try:
        with open(settings.ALIPAY_PRIVATE_KEY_PATH, "r", encoding="utf-8") as f:
            app_private_key_string = f.read()
        with open(settings.ALIPAY_PUBLIC_KEY_PATH, "r", encoding="utf-8") as f:
            alipay_public_key_string = f.read()
        return AliPay(
            appid=settings.ALIPAY_APP_ID,
            app_notify_url=_build_provider_notify_url("alipay"),
            app_private_key_string=app_private_key_string,
            alipay_public_key_string=alipay_public_key_string,
            sign_type="RSA2",
            debug=settings.ALIPAY_DEBUG,
        )
    except Exception as exc:
        logger.warning(f"Failed to init Alipay client: {exc}")
        return None


def _init_wechat_client() -> Optional[WeChatPay]:
    if not settings.WECHAT_APP_ID:
        return None
    try:
        with open(settings.WECHAT_PRIVATE_KEY_PATH, "r", encoding="utf-8") as f:
            wechat_private_key = f.read()
        return WeChatPay(
            wechatpay_type=WeChatPayType.NATIVE,
            mchid=settings.WECHAT_MCH_ID,
            private_key=wechat_private_key,
            cert_serial_no=settings.WECHAT_CERT_SERIAL_NO,
            apiv3_key=settings.WECHAT_API_V3_KEY,
            appid=settings.WECHAT_APP_ID,
            notify_url=_build_provider_notify_url("wechat"),
            logger=logger,
        )
    except Exception as exc:
        logger.warning(f"Failed to init WeChat client: {exc}")
        return None


alipay_client = _init_alipay_client()
wechat_client = _init_wechat_client()


def generate_order_no() -> str:
    return f"PAY{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _merge_order_extra(order: PaymentOrder, updates: dict[str, Any]) -> dict[str, Any]:
    data = dict(order.extra_data or {})
    data.update(updates)
    order.extra_data = data
    return data


def _extract_failure_reason(order: PaymentOrder) -> Optional[str]:
    if isinstance(order.extra_data, dict):
        reason = order.extra_data.get("failure_reason")
        if reason:
            return str(reason)
    return None


def _to_payment_schema(order: PaymentOrder) -> PaymentOrderSchema:
    return PaymentOrderSchema(
        id=order.id,
        order_no=order.order_no,
        user_id=order.user_id,
        amount=order.amount,
        payment_method=str(_enum_value(order.payment_method)),
        status=str(_enum_value(order.status)),
        product_type=order.product_type or "",
        created_at=order.created_at,
        paid_at=order.paid_at,
        transaction_id=order.transaction_id,
        extra_data=order.extra_data if isinstance(order.extra_data, dict) else None,
        failure_reason=_extract_failure_reason(order),
    )


def _build_frontend_base_url(request: Request) -> str:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get(
        "host", request.url.netloc
    )
    return f"{forwarded_proto}://{forwarded_host}".rstrip("/")


async def _mark_order_failed(
    db: AsyncSession,
    order: PaymentOrder,
    reason: str,
    provider_payload: Optional[dict[str, Any]] = None,
) -> None:
    order.status = PaymentStatus.FAILED
    payload: dict[str, Any] = {
        "failure_reason": reason,
        "failed_at": datetime.now().isoformat(),
    }
    if provider_payload:
        payload["failure_payload"] = provider_payload
    _merge_order_extra(order, payload)
    db.add(order)
    await db.flush()


async def _notify_payment_success(
    db: AsyncSession,
    order: PaymentOrder,
    *,
    is_wallet_topup: bool,
) -> None:
    title = "钱包充值成功" if is_wallet_topup else "支付成功"
    action = "充值" if is_wallet_topup else "支付"
    content = (
        f"您的{action}已完成。订单号：{order.order_no}，金额：{float(order.amount):.2f} 元。"
    )
    try:
        msg = await crud_message.create(
            db,
            obj_in=MessageCreate(
                title=title,
                content=content,
                receiver_id=order.user_id,
                type=MessageType.SYSTEM,
            ),
        )
    except Exception as exc:
        logger.error(f"Create payment success message failed for order {order.order_no}: {exc}")
        return

    try:
        from api.v1.endpoints.ws_controller import manager

        payload = {
            "type": "new_message",
            "data": {
                "id": str(msg.id),
                "title": msg.title,
                "content": msg.content,
            },
        }
        await manager.send_personal_message(json.dumps(payload), order.user_id)
    except Exception as exc:
        logger.error(f"WebSocket payment success notify failed for order {order.order_no}: {exc}")


async def _handle_payment_success_without_lock(
    db: AsyncSession, order: PaymentOrder, transaction_id: str
) -> None:
    if str(_enum_value(order.status)) == PaymentStatus.PAID.value:
        return

    order.status = PaymentStatus.PAID
    order.paid_at = datetime.now()
    order.transaction_id = transaction_id

    extra_data = dict(order.extra_data or {})
    extra_data.pop("failure_reason", None)
    extra_data["paid_at"] = order.paid_at.isoformat()
    order.extra_data = extra_data

    product_code = ""
    if isinstance(order.product_snapshot, dict):
        product_code = str(order.product_snapshot.get("code", ""))
    is_wallet_topup = bool(
        product_code.startswith("wallet_topup") or (order.product_type == "wallet_topup")
    )

    if is_wallet_topup:
        await crud_wallet.wallet.add_balance(
            db=db,
            user_id=order.user_id,
            amount=order.amount,
            source=f"Top-up: {order.order_no}",
            order_no=order.order_no,
            transaction_type=TransactionType.DEPOSIT,
        )

    db.add(order)
    await db.flush()
    await _notify_payment_success(db, order, is_wallet_topup=is_wallet_topup)


async def handle_payment_success(db: AsyncSession, order: PaymentOrder, transaction_id: str) -> None:
    if str(_enum_value(order.status)) == PaymentStatus.PAID.value:
        return

    lock_key = redis_manager.make_key(f"lock:payment_callback:{order.order_no}")
    try:
        async with redis_manager.redis_client.lock(lock_key, timeout=30, blocking_timeout=3):
            await db.refresh(order)
            await _handle_payment_success_without_lock(db, order, transaction_id)
    except Exception as exc:
        logger.warning(f"Payment lock unavailable, fallback to unlocked processing: {exc}")
        await _handle_payment_success_without_lock(db, order, transaction_id)


@router.get("/my/orders", response_model=PaymentOrderPage)
async def get_my_orders(
    page: int = 1,
    size: int = 20,
    status: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    page = max(page, 1)
    size = min(max(size, 1), 100)
    skip = (page - 1) * size

    items = await crud_payment.payment_order.list_orders(
        db=db,
        user_id=current_user.id,
        status=status,
        skip=skip,
        limit=size,
    )
    total = await crud_payment.payment_order.count_orders(
        db=db,
        user_id=current_user.id,
        status=status,
    )
    return PaymentOrderPage(
        items=[_to_payment_schema(order) for order in items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/admin/orders", response_model=PaymentOrderPage)
async def admin_get_orders(
    page: int = 1,
    size: int = 20,
    status: Optional[str] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
    order_no: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    admin_user: dict = Depends(get_current_admin_user),
):
    page = max(page, 1)
    size = min(max(size, 1), 100)
    skip = (page - 1) * size

    items = await crud_payment.payment_order.list_orders(
        db=db,
        user_id=user_id,
        status=status,
        order_no=order_no,
        skip=skip,
        limit=size,
    )
    total = await crud_payment.payment_order.count_orders(
        db=db,
        user_id=user_id,
        status=status,
        order_no=order_no,
    )
    return PaymentOrderPage(
        items=[_to_payment_schema(order) for order in items],
        total=total,
        page=page,
        size=size,
    )


@router.post("/admin/repair/{order_no}")
async def admin_repair_order(
    order_no: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_user: dict = Depends(get_current_admin_user),
):
    order = await crud_payment.payment_order.get_by_order_no(db, order_no)
    if not order:
        raise AppException(status_code=404, code=StatusCode.BUSINESS_ERROR, message="Order not found")

    if str(_enum_value(order.status)) == PaymentStatus.PAID.value:
        return {"ok": True, "message": "Order already paid", "order": _to_payment_schema(order)}

    transaction_id = f"MANUAL_{uuid.uuid4().hex[:20].upper()}"
    _merge_order_extra(
        order,
        {
            "manual_repair": {
                "admin_id": admin_user.id,
                "ip": request.client.host if request.client else None,
                "at": datetime.now().isoformat(),
            }
        },
    )

    await handle_payment_success(db, order, transaction_id)
    return {
        "ok": True,
        "message": "Manual repair completed",
        "order": _to_payment_schema(order),
    }


@router.post("/admin/mark-failed/{order_no}")
async def admin_mark_order_failed(
    order_no: str,
    reason: str = Query(..., min_length=2, max_length=200),
    db: AsyncSession = Depends(get_db),
    admin_user: dict = Depends(get_current_admin_user),
):
    order = await crud_payment.payment_order.get_by_order_no(db, order_no)
    if not order:
        raise AppException(status_code=404, code=StatusCode.BUSINESS_ERROR, message="Order not found")

    if str(_enum_value(order.status)) == PaymentStatus.PAID.value:
        raise AppException(
            status_code=400,
            code=StatusCode.BUSINESS_ERROR,
            message="Paid order cannot be marked as failed",
        )

    await _mark_order_failed(
        db=db,
        order=order,
        reason=reason,
        provider_payload={"marked_by_admin": admin_user.id},
    )
    return {"ok": True, "message": "Order marked failed", "order": _to_payment_schema(order)}


@router.post("/refund/{order_no}")
async def refund_order(
    order_no: str,
    db: AsyncSession = Depends(get_db),
    admin_user: dict = Depends(get_current_admin_user),
):
    order = await crud_payment.payment_order.get_by_order_no(db, order_no)
    if not order:
        raise AppException(status_code=404, code=StatusCode.BUSINESS_ERROR, message="Order not found")
    if str(_enum_value(order.status)) != PaymentStatus.PAID.value:
        raise AppException(
            status_code=400,
            code=StatusCode.BUSINESS_ERROR,
            message=f"Order status is {order.status}, cannot refund",
        )

    method = str(_enum_value(order.payment_method))
    if method == PaymentMethod.WALLET.value:
        await crud_wallet.wallet.add_balance(
            db=db,
            user_id=order.user_id,
            amount=order.amount,
            source=f"Refund for {order.order_no}",
            order_no=order.order_no,
            transaction_type=TransactionType.REFUND,
        )
        order.status = PaymentStatus.REFUNDED
        db.add(order)
        await db.flush()
        return {"message": "Wallet refund successful"}

    if method == PaymentMethod.ALIPAY.value:
        if not alipay_client:
            raise ExternalServiceException(message="Alipay not configured")
        refund_kwargs: dict[str, Any] = {
            "out_trade_no": order_no,
            "refund_amount": order.amount,
            "out_request_no": f"REF_{order_no}",
        }
        if settings.ALIPAY_APP_AUTH_TOKEN:
            refund_kwargs["app_auth_token"] = settings.ALIPAY_APP_AUTH_TOKEN
        result = alipay_client.api_alipay_trade_refund(**refund_kwargs)
        if result.get("code") != "10000":
            raise AppException(
                status_code=400,
                code=StatusCode.BUSINESS_ERROR,
                message=f"Alipay refund failed: {result.get('sub_msg')}",
            )
        order.status = PaymentStatus.REFUNDED
        db.add(order)
        await db.flush()
        return {"message": "Alipay refund successful", "alipay_response": result}

    if method == PaymentMethod.WECHAT.value:
        if not wechat_client:
            raise ExternalServiceException(message="WeChat Pay not configured")
        result = wechat_client.refund(
            out_refund_no=f"REF_{order_no}",
            amount={
                "refund": int(order.amount * 100),
                "total": int(order.amount * 100),
                "currency": "CNY",
            },
            out_trade_no=order_no,
        )
        status_ = result.get("status")
        if status_ not in ["SUCCESS", "PROCESSING"]:
            raise AppException(
                status_code=400,
                code=StatusCode.BUSINESS_ERROR,
                message="WeChat refund failed",
            )
        order.status = PaymentStatus.REFUNDED
        db.add(order)
        await db.flush()
        return {"message": "WeChat refund initiated", "wechat_response": result}

    raise AppException(
        status_code=400,
        code=StatusCode.BUSINESS_ERROR,
        message="Unsupported payment method for refund",
    )


@router.post("/create", response_model=PaymentOrderResponse)
async def create_payment(
    request: Request,
    order_in: PaymentOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    lock_key = f"lock:create_order:{current_user.id}:{order_in.product_id or order_in.product_type}:{order_in.amount}"
    lock_redis_key = redis_manager.make_key(lock_key)
    lock_token = uuid.uuid4().hex
    lock_acquired = False

    try:
        try:
            lock_acquired = bool(
                await redis_manager.redis_client.set(lock_redis_key, lock_token, nx=True, ex=3)
            )
        except Exception as exc:
            logger.warning(f"Create order lock unavailable, continue without lock: {exc}")
            lock_acquired = True

        if not lock_acquired:
            raise AppException(
                status_code=429,
                code=StatusCode.TOO_MANY_REQUESTS,
                message="Too many requests, please try again later",
            )

        final_amount = order_in.amount
        product_snapshot = None
        product_type = order_in.product_type or "product"

        if order_in.product_id:
            product = await crud_product.product.get(db, id=order_in.product_id)
            if not product or not product.is_active:
                raise AppException(
                    status_code=400,
                    code=StatusCode.BUSINESS_ERROR,
                    message="Invalid or inactive product",
                )
            final_amount = float(product.price)
            product_type = order_in.product_type or product.category or product.code or "product"
            product_snapshot = {
                "name": product.name,
                "code": product.code,
                "price": product.price,
                "original_price": product.original_price,
            }
        elif order_in.product_type == "resume_analysis":
            raise AppException(
                status_code=400,
                code=StatusCode.BUSINESS_ERROR,
                message="Product ID required for resume analysis",
            )
        elif not final_amount or final_amount <= 0:
            raise AppException(
                status_code=400,
                code=StatusCode.BUSINESS_ERROR,
                message="Amount must be greater than 0",
            )

        order_no = generate_order_no()
        db_order = PaymentOrder(
            order_no=order_no,
            user_id=current_user.id,
            amount=float(final_amount),
            payment_method=_enum_value(order_in.payment_method),
            status=PaymentStatus.PENDING,
            product_type=product_type,
            product_id=order_in.product_id,
            product_snapshot=product_snapshot,
            extra_data=order_in.extra_data,
        )
        db.add(db_order)
        await db.flush()

        response = PaymentOrderResponse(
            order_no=order_no,
            amount=float(final_amount),
            status=PaymentStatus.PENDING.value,
        )

        method = str(_enum_value(order_in.payment_method))
        subject = f"Job Analysis - {product_type}"

        if method == PaymentMethod.ALIPAY.value:
            if not alipay_client:
                await _mark_order_failed(db, db_order, "Alipay is not configured")
                response.status = PaymentStatus.FAILED.value
                response.pay_params = {"reason": "Alipay is not configured"}
                return response
            try:
                return_url = f"{_build_frontend_base_url(request)}/my/wallet"
                pay_kwargs: dict[str, Any] = {
                    "out_trade_no": order_no,
                    "total_amount": float(final_amount),
                    "subject": subject,
                    "return_url": return_url,
                    "notify_url": _build_provider_notify_url("alipay"),
                }
                if settings.ALIPAY_APP_AUTH_TOKEN:
                    pay_kwargs["app_auth_token"] = settings.ALIPAY_APP_AUTH_TOKEN
                order_string = alipay_client.api_alipay_trade_page_pay(**pay_kwargs)
                gateway = (
                    "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
                    if settings.ALIPAY_DEBUG
                    else "https://openapi.alipay.com/gateway.do"
                )
                response.pay_url = f"{gateway}?{order_string}"
                return response
            except Exception as exc:
                await _mark_order_failed(db, db_order, f"Alipay create failed: {exc}")
                response.status = PaymentStatus.FAILED.value
                response.pay_params = {"reason": f"Alipay create failed: {exc}"}
                return response

        if method == PaymentMethod.WECHAT.value:
            if not wechat_client:
                await _mark_order_failed(db, db_order, "WeChat Pay is not configured")
                response.status = PaymentStatus.FAILED.value
                response.pay_params = {"reason": "WeChat Pay is not configured"}
                return response
            try:
                pay_kwargs = {
                    "description": subject,
                    "out_trade_no": order_no,
                    "amount": {"total": int(float(final_amount) * 100)},
                }
                code, message = wechat_client.pay(**pay_kwargs)
                result = json.loads(message) if isinstance(message, str) else (message or {})
                if code in [200, 201]:
                    response.qr_code_url = result.get("code_url")
                    return response
                await _mark_order_failed(
                    db,
                    db_order,
                    "WeChat pay create failed",
                    provider_payload={"code": code, "message": message},
                )
                response.status = PaymentStatus.FAILED.value
                response.pay_params = {"reason": "WeChat pay create failed"}
                return response
            except Exception as exc:
                await _mark_order_failed(db, db_order, f"WeChat pay create failed: {exc}")
                response.status = PaymentStatus.FAILED.value
                response.pay_params = {"reason": f"WeChat pay create failed: {exc}"}
                return response

        if method == PaymentMethod.WALLET.value:
            wallet = await crud_wallet.wallet.get_by_user(db, current_user.id)
            if not wallet or wallet.balance < float(final_amount):
                await _mark_order_failed(db, db_order, "Insufficient wallet balance")
                response.status = PaymentStatus.FAILED.value
                response.pay_params = {"reason": "Insufficient wallet balance"}
                return response

            success = await crud_wallet.wallet.consume_balance(
                db=db,
                user_id=current_user.id,
                amount=float(final_amount),
                description=f"Payment for {order_no}",
                order_no=order_no,
            )
            if not success:
                await _mark_order_failed(db, db_order, "Wallet payment failed")
                response.status = PaymentStatus.FAILED.value
                response.pay_params = {"reason": "Wallet payment failed"}
                return response

            await handle_payment_success(
                db=db,
                order=db_order,
                transaction_id=f"WALLET_{uuid.uuid4().hex[:20].upper()}",
            )
            response.status = PaymentStatus.PAID.value
            response.pay_params = {"message": "Payment successful"}
            return response

        await _mark_order_failed(db, db_order, f"Unsupported payment method: {method}")
        response.status = PaymentStatus.FAILED.value
        response.pay_params = {"reason": f"Unsupported payment method: {method}"}
        return response
    finally:
        if lock_acquired:
            try:
                unlock_script = """
                if redis.call("get", KEYS[1]) == ARGV[1] then
                    return redis.call("del", KEYS[1])
                else
                    return 0
                end
                """
                await redis_manager.redis_client.eval(unlock_script, 1, lock_redis_key, lock_token)
            except Exception as exc:
                logger.warning(f"Failed to release lock {lock_key}: {exc}")


@router.get("/check/{order_no}", response_model=PaymentOrderSchema)
async def check_order_status(
    order_no: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    order = await crud_payment.payment_order.get_by_order_no(db, order_no)
    if not order:
        raise AppException(status_code=404, code=StatusCode.BUSINESS_ERROR, message="Order not found")
    if order.user_id != current_user.id:
        raise PermissionDeniedException(message="Not authorized")
    return _to_payment_schema(order)


@router.post("/notify/alipay")
async def alipay_notify(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.form()
    data_dict = dict(data)
    signature = data_dict.pop("sign", "")
    if not alipay_client or not signature:
        return "fail"

    try:
        verified = alipay_client.verify(data_dict, signature)
    except Exception as exc:
        logger.error(f"Alipay verify error: {exc}")
        return "fail"

    if not verified:
        return "fail"

    out_trade_no = data_dict.get("out_trade_no")
    trade_no = data_dict.get("trade_no")
    trade_status = data_dict.get("trade_status")
    total_amount = float(data_dict.get("total_amount", 0))

    order = await crud_payment.payment_order.get_by_order_no(db, out_trade_no)
    if not order:
        return "success"

    if trade_status in ["TRADE_SUCCESS", "TRADE_FINISHED"]:
        if abs(total_amount - float(order.amount)) > 0.01:
            await _mark_order_failed(
                db,
                order,
                "Alipay callback amount mismatch",
                provider_payload={"total_amount": total_amount},
            )
            return "fail"
        await handle_payment_success(db, order, trade_no or f"ALIPAY_{uuid.uuid4().hex[:16]}")
        return "success"

    if trade_status in ["TRADE_CLOSED"]:
        await _mark_order_failed(
            db,
            order,
            "Trade closed by provider",
            provider_payload={"trade_status": trade_status},
        )
        return "success"

    return "success"


@router.post("/notify/wechat")
async def wechat_notify(request: Request, db: AsyncSession = Depends(get_db)):
    if not wechat_client:
        return {"code": "FAIL", "message": "Config error"}

    headers = dict(request.headers)
    body = await request.body()

    try:
        callback_data = wechat_client.callback(headers, body)
        decoded_data = callback_data
        try:
            # Some sdk versions require explicit decrypt for callback payload.
            decoded_data = wechat_client.decrypt_callback(headers, body)
        except Exception:
            pass

        if isinstance(decoded_data, dict) and decoded_data.get("event_type") == "TRANSACTION.SUCCESS":
            decoded_data = decoded_data.get("resource", decoded_data)

        out_trade_no = decoded_data.get("out_trade_no")
        transaction_id = decoded_data.get("transaction_id")
        total_fee = (decoded_data.get("amount") or {}).get("total", 0)

        if not out_trade_no:
            return {"code": "FAIL", "message": "Missing out_trade_no"}

        order = await crud_payment.payment_order.get_by_order_no(db, out_trade_no)
        if not order:
            return {"code": "SUCCESS", "message": "OK"}

        expected_fee = int(float(order.amount) * 100)
        if total_fee and int(total_fee) != expected_fee:
            await _mark_order_failed(
                db,
                order,
                "WeChat callback amount mismatch",
                provider_payload={"total_fee": total_fee, "expected_fee": expected_fee},
            )
            return {"code": "FAIL", "message": "Amount mismatch"}

        await handle_payment_success(
            db=db,
            order=order,
            transaction_id=transaction_id or f"WECHAT_{uuid.uuid4().hex[:16]}",
        )
        return {"code": "SUCCESS", "message": "OK"}
    except Exception as exc:
        logger.error(f"WeChat notify error: {exc}")
        return {"code": "FAIL", "message": str(exc)}
