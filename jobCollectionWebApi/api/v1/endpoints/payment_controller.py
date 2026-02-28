from core.logger import sys_logger as logger
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
from core.logger import sys_logger as logger
from schemas.payment import (
    PaymentOrderCreate, 
    PaymentOrderResponse, 
    PaymentNotifyResponse,
    PaymentOrderSchema
)
from alipay import AliPay

router = APIRouter()

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
    """鐢熸垚鍞竴璁㈠崟鍙? PAY + YYYYMMDDHHMMSS + Random"""
    return f"PAY{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

async def handle_payment_success(db: AsyncSession, order: PaymentOrder, transaction_id: str):
    """澶勭悊鏀粯鎴愬姛閫昏緫 (甯﹀垎甯冨紡閿?"""
    # 1. First Check
    if order.status == PaymentStatus.PAID:
        logger.info(f"Order {order.order_no} already paid. Skipping.")
        return

    # 2. Acquire Lock
    lock_key = f"lock:payment_callback:{order.order_no}"
    try:
        # 浣跨敤 redis-py 鐨?Lock 瀵硅薄
        async with redis_manager.redis_client.lock(
            redis_manager.make_key(lock_key), 
            timeout=30, # 閿佹寔鏈夋椂闂?
            blocking_timeout=5 # 绛夊緟閿佹椂闂?
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
            
            # --- 鑷姩鍙戣揣閫昏緫 ---
            # 妫€鏌ユ槸鍚︽槸浣欓鍏呭€?
            should_commit = True 
            try:
                # 灏濊瘯浠庡揩鐓ц幏鍙栧晢鍝佷俊鎭紝濡傛灉娌℃湁蹇収鍒欐煡璇㈡暟鎹簱(鍙€?
                product_code = ""
                if order.product_snapshot:
                    product_code = order.product_snapshot.get("code", "")
                
                # 绠€鍗曞垽鏂? code 浠?wallet_topup 寮€澶达紝鎴栬€?product_type 鏄?wallet_topup
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
                # 鍏朵粬浜у搧绫诲瀷鐨勫彂璐ч€昏緫鍙互鍦ㄨ繖閲屾墿灞?
            except Exception as e:
                logger.error(f"Failed to deliver product for order {order.order_no}: {e}")
                # 濡傛灉鍙戣揣澶辫触锛屾槸鍚﹀洖婊氱姸鎬侊紵鎴栬€呮爣璁颁负 'paid_but_delivery_failed'锛?
                # 杩欓噷鏆備笖鎶涘嚭寮傚父鍥炴粴鏁翠釜浜嬪姟锛屼緷闈犲洖璋冮噸璇?
                should_commit = False
                raise e
            
            if should_commit:
                db.add(order)
                await db.commit()
                await db.refresh(order)
            
            logger.info(f"Order {order.order_no} paid successfully. Transaction ID: {transaction_id}")
            
    except Exception as e:
        logger.error(f"Error handling payment success for {order.order_no}: {e}")
        # 濡傛灉鑾峰彇閿佸け璐ユ垨鎵ц鍑洪敊锛屾姏鍑哄紓甯镐互渚夸笂灞傚喅瀹氭槸鍚﹂噸璇曪紙瀵逛簬鍥炶皟锛岄€氬父杩斿洖閿欒璁╃涓夋柟閲嶈瘯锛?
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
    閫€娆炬帴鍙?(浠呯鐞嗗憳)
    鏀寔鑷姩閫€娆? Wallet, Alipay, Wechat
    """
    order = await crud_payment.payment_order.get_by_order_no(db, order_no)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if order.status != PaymentStatus.PAID:
        raise HTTPException(status_code=400, detail=f"Order status is {order.status}, cannot refund")
        
    # 1. 閽卞寘閫€娆?
    if order.payment_method == "wallet": # PaymentMethod.WALLET
        try:
            # 鍘熻矾閫€鍥炰綑棰?
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

    # 2. 鏀粯瀹濋€€娆?
    elif order.payment_method == PaymentMethod.ALIPAY:
        if not alipay_client:
             raise HTTPException(status_code=500, detail="Alipay not configured")
        
        try:
            # 璋冪敤閫€娆炬帴鍙?
            result = alipay_client.api_alipay_trade_refund(
                out_trade_no=order_no,
                refund_amount=order.amount,
                out_request_no=f"REF_{order_no}" # 閮ㄥ垎閫€娆鹃渶瑕侊紝鍏ㄩ閫€娆惧叾瀹炲彲閫?
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

    # 3. 寰俊閫€娆?
    elif order.payment_method == PaymentMethod.WECHAT:
        if not wechat_client:
             raise HTTPException(status_code=500, detail="WeChat Pay not configured")
        
        try:
            # 寰俊閫€娆鹃渶瑕佽瘉涔?
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
    """鍒涘缓鏀粯璁㈠崟"""
    # 0. 闃叉姈妫€鏌? 闃叉3绉掑唴閲嶅鐐瑰嚮 (Redis Lock)
    # 閿侀敭: lock:create_order:{user_id}:{product_id_or_type}:{amount}
    lock_key = f"lock:create_order:{current_user.id}:{order_in.product_id or order_in.product_type}:{order_in.amount}"
    
    # 灏濊瘯鑾峰彇闈為樆濉為攣锛屽鏋滆幏鍙栧け璐ヨ鏄庤姹傝繃蹇?
    lock_redis_key = redis_manager.make_key(lock_key)
    lock_token = uuid.uuid4().hex
    acquired = await redis_manager.redis_client.set(lock_redis_key, lock_token, nx=True, ex=3)
    if not acquired:
        raise HTTPException(status_code=429, detail="Too many requests, please try again later")
        
    try:
        # 0.1 楠岃瘉鍙傛暟涓庤幏鍙栦环鏍?
        final_amount = order_in.amount
        product_snapshot = None
        
        if order_in.product_id:
            product = await crud_product.product.get(db, id=order_in.product_id)
            if not product or not product.is_active:
                 raise HTTPException(status_code=400, detail="Invalid or inactive product")
            final_amount = product.price
            # 璁板綍蹇収
            product_snapshot = {
                "name": product.name,
                "code": product.code,
                "price": product.price,
                "original_price": product.original_price
            }
    
        # 寮哄埗閲戦鏍￠獙: 濡傛灉鏄畝鍘嗗垎鏋愮瓑鍥哄畾浠锋牸鏈嶅姟锛屽繀椤婚€氳繃 product_id 鑾峰彇浠锋牸
        elif order_in.product_type == "resume_analysis":
             raise HTTPException(status_code=400, detail="Product ID required for resume analysis")
             
        elif not final_amount or final_amount <= 0:
             raise HTTPException(status_code=400, detail="Amount must be greater than 0")
             
        # 1. 鐢熸垚璁㈠崟
        order_no = generate_order_no()
        
        # 鎵嬪姩鏋勯€?PaymentOrder 瀵硅薄浠ユ敮鎸?product_id (濡傛灉 crud_payment 鏈洿鏂版敮鎸?obj_in 鍖呭惈 product_id)
        # 鎴栬€呮洿鏂?crud_payment.create_order
        # 杩欓噷鎴戜滑鐩存帴浣跨敤 DB 鎿嶄綔姣旇緝鐏垫椿
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
        
        # 2. 璋冪敤鏀粯鎺ュ彛
        if order_in.payment_method == PaymentMethod.ALIPAY:
            if not alipay_client:
                raise HTTPException(status_code=500, detail="Alipay not configured")
            
            # 鐢佃剳缃戠珯鏀粯
            order_string = alipay_client.api_alipay_trade_page_pay(
                out_trade_no=order_no,
                total_amount=float(order_in.amount),
                subject=f"Job Analysis - {order_in.product_type}",
                return_url="http://localhost:3000/payment/success", # 鍓嶇鍥炶皟椤甸潰
                notify_url=f"{settings.PAYMENT_NOTIFY_BASE_URL}/alipay"
            )
            # 鎷兼帴缃戝叧鍦板潃
            gateway = "https://openapi-sandbox.dl.alipaydev.com/gateway.do" if settings.ALIPAY_DEBUG else "https://openapi.alipay.com/gateway.do"
            response.pay_url = f"{gateway}?{order_string}"
            
        elif order_in.payment_method == PaymentMethod.WECHAT:
            if not wechat_client:
                raise HTTPException(status_code=500, detail="WeChat Pay not configured")
                
            code, message = wechat_client.pay(
                description=f"Job Analysis - {order_in.product_type}",
                out_trade_no=order_no,
                amount={'total': int(order_in.amount * 100)}, # 鍒?
                payer={'openid': current_user.wechat_info.openid} if current_user.wechat_info else None
            )
            
            result = json.loads(message)
            if code in [200, 201]:
                 response.qr_code_url = result.get('code_url')
            else:
                 logger.error(f"WeChat Pay Error: {message}")
                 raise HTTPException(status_code=500, detail="WeChat Pay failed")
    
        elif order_in.payment_method == "wallet": # PaymentMethod.WALLET (use string to avoid import circle if any)
            # 閽卞寘鏀粯閫昏緫
            wallet = await crud_wallet.wallet.get_by_user(db, current_user.id)
            if not wallet or wallet.balance < final_amount:
                raise HTTPException(status_code=400, detail="Insufficient wallet balance")
                
            # 鎵ｆ
            success = await crud_wallet.wallet.consume_balance(
                db, 
                user_id=current_user.id, 
                amount=final_amount, 
                description=f"Payment for {order_no}",
                order_no=order_no
            )
            
            if success:
                # 鏇存柊璁㈠崟鐘舵€佷负宸叉敮浠?
                order = await crud_payment.payment_order.get_by_order_no(db, order_no) # Re-fetch to be safe
                if order:
                    await handle_payment_success(db, order, transaction_id=f"WALLET_{uuid.uuid4().hex}")
                    response.status = PaymentStatus.PAID
                    response.pay_params = {"message": "Payment successful"}
            else:
                 raise HTTPException(status_code=400, detail="Wallet payment failed")

    finally:
        # 閲婃斁閿?(铏界劧鏈塗TL锛屼絾鏈€濂戒富鍔ㄩ噴鏀惧鏋滄湭 crash)
        try:
            unlock_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            await redis_manager.redis_client.eval(unlock_script, 1, lock_redis_key, lock_token)
        except Exception as e:
            logger.warning(f"Failed to release lock {lock_key}: {e}")

    return response

@router.get("/check/{order_no}", response_model=PaymentOrderSchema)
async def check_order_status(
    order_no: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """鏌ヨ璁㈠崟鐘舵€?"""
    order = await crud_payment.payment_order.get_by_order_no(db, order_no)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    # 鏉冮檺妫€鏌?
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    # 濡傛灉杩樻槸 Pending锛屽彲浠ヤ富鍔ㄥ幓绗笁鏂规煡涓€涓?(Draft implementation)
    # ...
    
    return order

@router.post("/notify/alipay")
async def alipay_notify(request: Request, db: AsyncSession = Depends(get_db)):
    """鏀粯瀹濆紓姝ラ€氱煡"""
    data = await request.form()
    data_dict = dict(data)
    
    signature = data_dict.pop("sign")
    
    # 楠岃瘉绛惧悕
    if alipay_client and alipay_client.verify(data_dict, signature):
        trade_status = data_dict.get("trade_status")
        out_trade_no = data_dict.get("out_trade_no")
        trade_no = data_dict.get("trade_no")
        
        if trade_status in ["TRADE_SUCCESS", "TRADE_FINISHED"]:
            order = await crud_payment.payment_order.get_by_order_no(db, out_trade_no)
            if order:
                # 鏍￠獙閲戦
                total_amount = float(data_dict.get("total_amount", 0))
                if abs(total_amount - order.amount) > 0.01:
                    logger.critical(f"Amount mismatch for order {out_trade_no}: expected {order.amount}, got {total_amount}")
                    return "fail"

                await handle_payment_success(db, order, trade_no)
                
        return "success"
    
    return "fail"

@router.post("/notify/wechat")
async def wechat_notify(request: Request, db: AsyncSession = Depends(get_db)):
    """寰俊鏀粯寮傛閫氱煡"""
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
                total_fee = amount_data.get('total', 0) # 鍒?

                order = await crud_payment.payment_order.get_by_order_no(db, out_trade_no)
                if order:
                     # 鏍￠獙閲戦
                    expected_fee = int(order.amount * 100)
                    if total_fee != expected_fee:
                        logger.critical(f"Amount mismatch for Wechat order {out_trade_no}: expected {expected_fee}, got {total_fee}")
                        # 搴旇杩斿洖澶辫触锛岃寰俊閲嶈瘯(鎴栬€呬汉宸ュ鐞?
                        return {"code": "FAIL", "message": "Amount mismatch"}

                    await handle_payment_success(db, order, transaction_id)
                    
            return {"code": "SUCCESS", "message": "OK"}
        except Exception as e:
            logger.error(f"WeChat Notify Error: {e}")
            return {"code": "FAIL", "message": str(e)}
            
    return {"code": "FAIL", "message": "Config error"}
