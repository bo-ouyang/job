import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from wechatpayv3 import WeChatPay, WeChatPayType

from jobCollectionWebApi.config import settings
from dependencies import get_db, get_current_user
from crud import payment as crud_payment
from crud import product as crud_product
from crud import wallet as crud_wallet
from common.databases.models.payment import PaymentOrder, PaymentStatus, PaymentMethod
from common.databases.RedisManager import redis_manager
import logging
from schemas.payment import (
    PaymentOrderCreate, 
    PaymentOrderResponse, 
    PaymentNotifyResponse,
    PaymentOrderSchema
)

router = APIRouter()
logger = logging.getLogger(__name__)

# --- SDK Initialization ---

# Alipay Init
alipay_client = None
if settings.ALIPAY_APP_ID:
    try:
        app_private_key_string = open(settings.ALIPAY_PRIVATE_KEY_PATH).read()
        alipay_public_key_string = open(settings.ALIPAY_PUBLIC_KEY_PATH).read()
        
        alipay_client = AliPay(
            appid=settings.ALIPAY_APP_ID,
            app_notify_url=f"{settings.PAYMENT_NOTIFY_BASE_URL}/alipay",
            app_private_key_string=app_private_key_string,
            alipay_public_key_string=alipay_public_key_string,
            sign_type="RSA2",
            debug=settings.ALIPAY_DEBUG
        )
    except Exception as e:
        logger.warning(f"Failed to init Alipay: {e}")

# WeChat Pay Init
wechat_client = None
if settings.WECHAT_APP_ID:
    try:
        with open(settings.WECHAT_PRIVATE_KEY_PATH) as f:
            wechat_private_key = f.read()
            
        wechat_client = WeChatPay(
            wechatpay_type=WeChatPayType.NATIVE,
            mchid=settings.WECHAT_MCH_ID,
            private_key=wechat_private_key,
            cert_serial_no=settings.WECHAT_CERT_SERIAL_NO,
            apiv3_key=settings.WECHAT_API_V3_KEY,
            appid=settings.WECHAT_APP_ID,
            notify_url=f"{settings.PAYMENT_NOTIFY_BASE_URL}/wechat",
            logger=logger
        )
    except Exception as e:
        logger.warning(f"Failed to init WeChat Pay: {e}")


# --- Helpers ---

def generate_order_no() -> str:
    """生成唯一订单号: PAY + YYYYMMDDHHMMSS + Random"""
    return f"PAY{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

async def handle_payment_success(db: AsyncSession, order: PaymentOrder, transaction_id: str):
    """处理支付成功逻辑 (带分布式锁)"""
    # 1. First Check
    if order.status == PaymentStatus.PAID:
        logger.info(f"Order {order.order_no} already paid. Skipping.")
        return

    # 2. Acquire Lock
    lock_key = f"lock:payment_callback:{order.order_no}"
    try:
        # 使用 redis-py 的 Lock 对象
        async with redis_manager.redis_client.lock(
            redis_manager.make_key(lock_key), 
            timeout=30, # 锁持有时间
            blocking_timeout=5 # 等待锁时间
        ):
            # 3. Double Check (Refresh from DB inside lock)
            await db.refresh(order)
            if order.status == PaymentStatus.PAID:
                logger.info(f"Order {order.order_no} already paid (detected inside lock). Skipping.")
                return
                
            # 4. Do Update
            order.status = PaymentStatus.PAID
            order.paid_at = datetime.now()
            order.transaction_id = transaction_id
            
            # --- 自动发货逻辑 ---
            # 检查是否是余额充值
            should_commit = True 
            try:
                # 尝试从快照获取商品信息，如果没有快照则查询数据库(可选)
                product_code = ""
                if order.product_snapshot:
                    product_code = order.product_snapshot.get("code", "")
                
                # 简单判断: code 以 wallet_topup 开头，或者 product_type 是 wallet_topup
                is_topup = False
                if product_code and product_code.startswith("wallet_topup"):
                    is_topup = True
                elif order.product_type == "wallet_topup":
                    is_topup = True
                    
                if is_topup:
                    logger.info(f"Processing wallet top-up for order {order.order_no}")
                    await crud_wallet.wallet.add_balance(
                        db, 
                        user_id=order.user_id, 
                        amount=order.amount, 
                        source=f"Top-up: {order.order_no}",
                        order_no=order.order_no
                    )
                # 其他产品类型的发货逻辑可以在这里扩展
            except Exception as e:
                logger.error(f"Failed to deliver product for order {order.order_no}: {e}")
                # 如果发货失败，是否回滚状态？或者标记为 'paid_but_delivery_failed'？
                # 这里暂且抛出异常回滚整个事务，依靠回调重试
                should_commit = False
                raise e
            
            if should_commit:
                db.add(order)
                await db.commit()
                await db.refresh(order)
            
            logger.info(f"Order {order.order_no} paid successfully. Transaction ID: {transaction_id}")
            
    except Exception as e:
        logger.error(f"Error handling payment success for {order.order_no}: {e}")
        # 如果获取锁失败或执行出错，抛出异常以便上层决定是否重试（对于回调，通常返回错误让第三方重试）
        raise e

from dependencies import get_current_admin_user
from common.databases.models.wallet import TransactionType

@router.post("/refund/{order_no}")
async def refund_order(
    order_no: str,
    db: AsyncSession = Depends(get_db),
    admin_user: dict = Depends(get_current_admin_user)
):
    """
    退款接口 (仅管理员)
    支持自动退款: Wallet, Alipay, Wechat
    """
    order = await crud_payment.payment_order.get_by_order_no(db, order_no)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if order.status != PaymentStatus.PAID:
        raise HTTPException(status_code=400, detail=f"Order status is {order.status}, cannot refund")
        
    # 1. 钱包退款
    if order.payment_method == "wallet": # PaymentMethod.WALLET
        try:
            # 原路退回余额
            await crud_wallet.wallet.add_balance(
                db, 
                user_id=order.user_id, 
                amount=order.amount, 
                source=f"Refund for {order.order_no}",
                order_no=order.order_no,
                transaction_type=TransactionType.REFUND
            )
            order.status = PaymentStatus.REFUNDED
            db.add(order)
            await db.commit()
            return {"message": "Wallet refund successful"}
        except Exception as e:
            logger.error(f"Wallet refund failed: {e}")
            raise HTTPException(status_code=500, detail="Wallet refund failed")

    # 2. 支付宝退款
    elif order.payment_method == PaymentMethod.ALIPAY:
        if not alipay_client:
             raise HTTPException(status_code=500, detail="Alipay not configured")
        
        try:
            # 调用退款接口
            result = alipay_client.api_alipay_trade_refund(
                out_trade_no=order_no,
                refund_amount=order.amount,
                out_request_no=f"REF_{order_no}" # 部分退款需要，全额退款其实可选
            )
            if result.get("code") == "10000":
                order.status = PaymentStatus.REFUNDED
                db.add(order)
                await db.commit()
                return {"message": "Alipay refund successful", "alipay_response": result}
            else:
                logger.error(f"Alipay refund failed: {result}")
                raise HTTPException(status_code=400, detail=f"Alipay refund failed: {result.get('sub_msg')}")
        except Exception as e:
            logger.error(f"Alipay refund exception: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # 3. 微信退款
    elif order.payment_method == PaymentMethod.WECHAT:
        if not wechat_client:
             raise HTTPException(status_code=500, detail="WeChat Pay not configured")
        
        try:
            # 微信退款需要证书
            # SDK helper might need raw request for refund if not wrapped
            # wechatpayv3 legacy/native might differ. Assuming standard usage:
            result = wechat_client.refund(
                out_refund_no=f"REF_{order_no}",
                amount={'refund': int(order.amount * 100), 'total': int(order.amount * 100), 'currency': 'CNY'},
                out_trade_no=order_no
            )
            # Check result status... usually sync response
            status_ = result.get('status')
            if status_ in ['SUCCESS', 'PROCESSING']:
                order.status = PaymentStatus.REFUNDED
                db.add(order)
                await db.commit()
                return {"message": "WeChat refund initiated", "wechat_response": result}
            else:
                 logger.error(f"WeChat refund failed: {result}")
                 raise HTTPException(status_code=400, detail="WeChat refund failed")

        except Exception as e:
            logger.error(f"WeChat refund exception: {e}")
            raise HTTPException(status_code=500, detail=str(e))
            
    else:
        raise HTTPException(status_code=400, detail="Unsupported payment method for auto refund")



# --- Endpoints ---

@router.post("/create", response_model=PaymentOrderResponse)
async def create_payment(
    order_in: PaymentOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """创建支付订单"""
    # 0. 防抖检查: 防止3秒内重复点击 (Redis Lock)
    # 锁键: lock:create_order:{user_id}:{product_id_or_type}:{amount}
    lock_key = f"lock:create_order:{current_user.id}:{order_in.product_id or order_in.product_type}:{order_in.amount}"
    
    # 尝试获取非阻塞锁，如果获取失败说明请求过快
    lock = redis_manager.redis_client.lock(
        redis_manager.make_key(lock_key),
        timeout=3, # 锁自动过期时间 3秒
        blocking_timeout=0 # 非阻塞模式
    )
    
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Too many requests, please try again later")
        
    try:
        # 0.1 验证参数与获取价格
        final_amount = order_in.amount
        product_snapshot = None
        
        if order_in.product_id:
            product = await crud_product.product.get(db, id=order_in.product_id)
            if not product or not product.is_active:
                 raise HTTPException(status_code=400, detail="Invalid or inactive product")
            final_amount = product.price
            # 记录快照
            product_snapshot = {
                "name": product.name,
                "code": product.code,
                "price": product.price,
                "original_price": product.original_price
            }
    
        # 强制金额校验: 如果是简历分析等固定价格服务，必须通过 product_id 获取价格
        elif order_in.product_type == "resume_analysis":
             raise HTTPException(status_code=400, detail="Product ID required for resume analysis")
             
        elif not final_amount or final_amount <= 0:
             raise HTTPException(status_code=400, detail="Amount must be greater than 0")
             
        # 1. 生成订单
        order_no = generate_order_no()
        
        # 手动构造 PaymentOrder 对象以支持 product_id (如果 crud_payment 未更新支持 obj_in 包含 product_id)
        # 或者更新 crud_payment.create_order
        # 这里我们直接使用 DB 操作比较灵活
        db_order = PaymentOrder(
            order_no=order_no,
            user_id=current_user.id,
            amount=final_amount,
            payment_method=order_in.payment_method,
            product_type=order_in.product_type or "product",
            product_id=order_in.product_id,
            product_snapshot=product_snapshot,
            extra_data=order_in.extra_data,
            status=PaymentStatus.PENDING
        )
        db.add(db_order)
        await db.flush()
        await db.refresh(db_order)
        
        response = PaymentOrderResponse(
            order_no=order_no,
            amount=final_amount,
            status=PaymentStatus.PENDING
        )
        
        # 2. 调用支付接口
        if order_in.payment_method == PaymentMethod.ALIPAY:
            if not alipay_client:
                raise HTTPException(status_code=500, detail="Alipay not configured")
            
            # 电脑网站支付
            order_string = alipay_client.api_alipay_trade_page_pay(
                out_trade_no=order_no,
                total_amount=float(order_in.amount),
                subject=f"Job Analysis - {order_in.product_type}",
                return_url="http://localhost:3000/payment/success", # 前端回调页面
                notify_url=f"{settings.PAYMENT_NOTIFY_BASE_URL}/alipay"
            )
            # 拼接网关地址
            gateway = "https://openapi-sandbox.dl.alipaydev.com/gateway.do" if settings.ALIPAY_DEBUG else "https://openapi.alipay.com/gateway.do"
            response.pay_url = f"{gateway}?{order_string}"
            
        elif order_in.payment_method == PaymentMethod.WECHAT:
            if not wechat_client:
                raise HTTPException(status_code=500, detail="WeChat Pay not configured")
                
            code, message = wechat_client.pay(
                description=f"Job Analysis - {order_in.product_type}",
                out_trade_no=order_no,
                amount={'total': int(order_in.amount * 100)}, # 分
                payer={'openid': current_user.wechat_info.openid} if current_user.wechat_info else None
            )
            
            result = json.loads(message)
            if code in [200, 201]:
                 response.qr_code_url = result.get('code_url')
            else:
                 logger.error(f"WeChat Pay Error: {message}")
                 raise HTTPException(status_code=500, detail="WeChat Pay failed")
    
        elif order_in.payment_method == "wallet": # PaymentMethod.WALLET (use string to avoid import circle if any)
            # 钱包支付逻辑
            wallet = await crud_wallet.wallet.get_by_user(db, current_user.id)
            if not wallet or wallet.balance < final_amount:
                raise HTTPException(status_code=400, detail="Insufficient wallet balance")
                
            # 扣款
            success = await crud_wallet.wallet.consume_balance(
                db, 
                user_id=current_user.id, 
                amount=final_amount, 
                description=f"Payment for {order_no}",
                order_no=order_no
            )
            
            if success:
                # 更新订单状态为已支付
                order = await crud_payment.payment_order.get_by_order_no(db, order_no) # Re-fetch to be safe
                if order:
                    await handle_payment_success(db, order, transaction_id=f"WALLET_{uuid.uuid4().hex}")
                    response.status = PaymentStatus.PAID
                    response.pay_params = {"message": "Payment successful"}
            else:
                 raise HTTPException(status_code=400, detail="Wallet payment failed")

    finally:
        # 释放锁 (虽然有TTL，但最好主动释放如果未 crash)
        try:
            if lock.locked():
                 lock.release()
        except Exception as e:
            logger.warning(f"Failed to release lock {lock_key}: {e}")

    return response

@router.get("/check/{order_no}", response_model=PaymentOrderSchema)
async def check_order_status(
    order_no: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """查询订单状态"""
    order = await crud_payment.payment_order.get_by_order_no(db, order_no)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    # 权限检查
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    # 如果还是 Pending，可以主动去第三方查一下 (Draft implementation)
    # ...
    
    return order

@router.post("/notify/alipay")
async def alipay_notify(request: Request, db: AsyncSession = Depends(get_db)):
    """支付宝异步通知"""
    data = await request.form()
    data_dict = dict(data)
    
    signature = data_dict.pop("sign")
    
    # 验证签名
    if alipay_client and alipay_client.verify(data_dict, signature):
        trade_status = data_dict.get("trade_status")
        out_trade_no = data_dict.get("out_trade_no")
        trade_no = data_dict.get("trade_no")
        
        if trade_status in ["TRADE_SUCCESS", "TRADE_FINISHED"]:
            order = await crud_payment.payment_order.get_by_order_no(db, out_trade_no)
            if order:
                # 校验金额
                total_amount = float(data_dict.get("total_amount", 0))
                if abs(total_amount - order.amount) > 0.01:
                    logger.critical(f"Amount mismatch for order {out_trade_no}: expected {order.amount}, got {total_amount}")
                    return "fail"

                await handle_payment_success(db, order, trade_no)
                
        return "success"
    
    return "fail"

@router.post("/notify/wechat")
async def wechat_notify(request: Request, db: AsyncSession = Depends(get_db)):
    """微信支付异步通知"""
    headers = request.headers
    body = await request.body()
    
    if wechat_client:
        try:
            result = wechat_client.callback(headers, body)
            if result and result.get('event_type') == 'TRANSACTION.SUCCESS':
                resource = result.get('resource')
                ciphertext = resource.get('ciphertext')
                nonce = resource.get('nonce')
                associated_data = resource.get('associated_data')
                
                decoded_data = wechat_client.decrypt_callback(headers, body) 
                # Note: helper inside callback might already decrypt? 
                # wechatpayv3 handling might differ slightly based on version.
                # Assuming result contains decrypted data or we use decrypt method.
                
                out_trade_no = decoded_data.get('out_trade_no')
                transaction_id = decoded_data.get('transaction_id')
                
                amount_data = decoded_data.get('amount', {})
                total_fee = amount_data.get('total', 0) # 分

                order = await crud_payment.payment_order.get_by_order_no(db, out_trade_no)
                if order:
                     # 校验金额
                    expected_fee = int(order.amount * 100)
                    if total_fee != expected_fee:
                        logger.critical(f"Amount mismatch for Wechat order {out_trade_no}: expected {expected_fee}, got {total_fee}")
                        # 应该返回失败，让微信重试(或者人工处理)
                        return {"code": "FAIL", "message": "Amount mismatch"}

                    await handle_payment_success(db, order, transaction_id)
                    
            return {"code": "SUCCESS", "message": "OK"}
        except Exception as e:
            logger.error(f"WeChat Notify Error: {e}")
            return {"code": "FAIL", "message": str(e)}
            
    return {"code": "FAIL", "message": "Config error"}
