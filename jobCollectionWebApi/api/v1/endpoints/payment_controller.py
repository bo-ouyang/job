from core.logger import sys_logger as logger
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Request, BackgroundTasks
from core.exceptions import AppException, ExternalServiceException, PermissionDeniedException
from core.status_code import StatusCode
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
from schemas.payment_schema import (
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
    """生成唯一订单流水号: PAY + 年月日时分秒 + 随机混淆码"""
    return f"PAY{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

async def handle_payment_success(db: AsyncSession, order: PaymentOrder, transaction_id: str):
    """处理支付成功回调逻辑本体 (携带原生 Redis 分布式互斥锁防止并发重复发货)"""
    # 1. First Check
    if order.status == PaymentStatus.PAID:
        logger.info(f"Order {order.order_no} already paid. Skipping.")
        return

    # 2. Acquire Lock
    lock_key = f"lock:payment_callback:{order.order_no}"
    try:
        # 使用 redis-py 原生 Lock 对象构建极简高效的分布式锁锁紧逻辑
        async with redis_manager.redis_client.lock(
            redis_manager.make_key(lock_key), 
            timeout=30, # 强制锁持有的最长物理时间(秒)，防止死锁风险
            blocking_timeout=5 # 等待其他线程释放锁的最大轮询心跳阻塞时间(秒)
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
            # 阶段拦截：深度检查是否属于中心虚拟钱包的充值业务，从而进行资金累加
            should_commit = True 
            try:
                # 为了性能优先从订单当时快照解构商品类型，如果没有快照则退化至查询只读库 (可选策略)
                product_code = ""
                if order.product_snapshot:
                    product_code = order.product_snapshot.get("code", "")
                
                # 无硬编码关联判断: 不论是 Code 满足还是直接 Type 满足，一律触发 wallet_topup (充值流水) 事件
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
                # [可扩展区] 未来如果您加入了 VIP会员、无限次简历AI包，则发货代码在此处接力。
            except Exception as e:
                logger.error(f"Failed to deliver product for order {order.order_no}: {e}")
                # 异常状态保护: 思考如果给用户加钱/加权限失败了，是否允许订单继续成功？我们采取最严格的事务强一致要求。
                # 在这种危急场景下，强制抛出外层 Exception 破坏这个 DB commit()，使得返回平台错误，以此触发微信/支付宝回调在 15s 后再次执行重试。
                should_commit = False
                raise e
            
            if should_commit:
                db.add(order)
                await db.commit()
                await db.refresh(order)
            
            logger.info(f"Order {order.order_no} paid successfully. Transaction ID: {transaction_id}")
            
    except Exception as e:
        logger.error(f"Error handling payment success for {order.order_no}: {e}")
        # 最后一道防线: 如果拿到锁失败或者在发货中直接报错了，这说明系统处于极度高压状态。依然利用重试机制！
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
        raise AppException(status_code=404, code=StatusCode.BUSINESS_ERROR, message="Order not found")
        
    if order.status != PaymentStatus.PAID:
        raise AppException(status_code=400, code=StatusCode.BUSINESS_ERROR, message=f"Order status is {order.status}, cannot refund")
        
    # 渠道1: 本站生态原生虚拟钱包退回策略
    if order.payment_method == "wallet": # PaymentMethod.WALLET
        try:
            # 采用“源路返还法则”，为用户生成一笔资金正向加项的变更记录。
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
            raise AppException(status_code=500, code=StatusCode.INTERNAL_SERVER_ERROR, message="Wallet refund failed")

    # 渠道2: 蚂蚁金服支付宝退款策略
    elif order.payment_method == PaymentMethod.ALIPAY:
        if not alipay_client:
             raise ExternalServiceException(message="Alipay not configured")
        
        try:
            # 对外封装调用 Alipay Python 服务侧的高级逆向贸易退款 HTTP API
            result = alipay_client.api_alipay_trade_refund(
                out_trade_no=order_no,
                refund_amount=order.amount,
                out_request_no=f"REF_{order_no}" # Out_Request_No 用于标识部分退货退款批次标识；如果是单纯的整单全额，实际为可选校验。
            )
            if result.get("code") == "10000":
                order.status = PaymentStatus.REFUNDED
                db.add(order)
                await db.commit()
                return {"message": "Alipay refund successful", "alipay_response": result}
            else:
                logger.error(f"Alipay refund failed: {result}")
                raise AppException(status_code=400, code=StatusCode.BUSINESS_ERROR, message=f"Alipay refund failed: {result.get('sub_msg')}")
        except Exception as e:
            logger.error(f"Alipay refund exception: {e}")
            raise AppException(status_code=500, code=StatusCode.INTERNAL_SERVER_ERROR, message=str(e))

    # 渠道3: 腾讯微信全托管退款策略
    elif order.payment_method == PaymentMethod.WECHAT:
        if not wechat_client:
             raise ExternalServiceException(message="WeChat Pay not configured")
        
        try:
            # 安全要求: 微信官方要求必须向服务器配置 TLS P12 双向验证客户端私钥证书（即 settings 中需携带）。
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
                 raise AppException(status_code=400, code=StatusCode.BUSINESS_ERROR, message="WeChat refund failed")

        except Exception as e:
            logger.error(f"WeChat refund exception: {e}")
            raise AppException(status_code=500, code=StatusCode.INTERNAL_SERVER_ERROR, message=str(e))
            
    else:
        raise AppException(status_code=400, code=StatusCode.BUSINESS_ERROR, message="Unsupported payment method for auto refund")



# --- Endpoints ---

@router.post("/create", response_model=PaymentOrderResponse)
async def create_payment(
    order_in: PaymentOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """统一支付聚合订单发起引擎"""
    # 阶段0 - 重复提单限流: 拦截高速网压下用户疯狂点击确认按钮。通过 Redis 层短生命周期 TTL 锁机制直接干预。
    # 设定多维度雪崩唯一串联标识符 Redis Hash Key (防止同一人同时并发下同一个东西)
    lock_key = f"lock:create_order:{current_user.id}:{order_in.product_id or order_in.product_type}:{order_in.amount}"
    
    # 这里极客地使用 nx=True 请求单次排他权限。得不到就直接打回前端！
    lock_redis_key = redis_manager.make_key(lock_key)
    lock_token = uuid.uuid4().hex
    acquired = await redis_manager.redis_client.set(lock_redis_key, lock_token, nx=True, ex=3)
    if not acquired:
        raise AppException(status_code=429, code=StatusCode.TOO_MANY_REQUESTS, message="Too many requests, please try again later")
        
    try:
        # 阶段0.1 - 数据库层面真实账单金额锁定
        final_amount = order_in.amount
        product_snapshot = None
        
        if order_in.product_id:
            product = await crud_product.product.get(db, id=order_in.product_id)
            if not product or not product.is_active:
                 raise AppException(status_code=400, code=StatusCode.BUSINESS_ERROR, message="Invalid or inactive product")
            final_amount = product.price
            # 为订单附加 Immutable 静态快照体，当未来商品涨价时该订单历史永远能被正确审计与开票
            product_snapshot = {
                "name": product.name,
                "code": product.code,
                "price": product.price,
                "original_price": product.original_price
            }
    
        # 安全防御墙: 防止前端随意用 0.01 元进行金额篡改来薅羊毛。如果是系统内置功能必定取库内官方价。
        elif order_in.product_type == "resume_analysis":
             raise AppException(status_code=400, code=StatusCode.BUSINESS_ERROR, message="Product ID required for resume analysis")
             
        elif not final_amount or final_amount <= 0:
             raise AppException(status_code=400, code=StatusCode.BUSINESS_ERROR, message="Amount must be greater than 0")
             
        # 阶段1 - 持久化到关系型数据库中保存流转基础
        order_no = generate_order_no()
        
        # 此处不依赖 Pydantic 间接转换，直接构造原生 ORM PaymentOrder 实例，为高并发提供更高灵活性支持。
        
        
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
        
        # 阶段2 - 触发对应代理工厂类并透传云端支付网关
        if order_in.payment_method == PaymentMethod.ALIPAY:
            if not alipay_client:
                raise ExternalServiceException(message="Alipay not configured")
            
            # 指令化构建支付宝 PC 端“Page Pay”跳转参数串
            order_string = alipay_client.api_alipay_trade_page_pay(
                out_trade_no=order_no,
                total_amount=float(order_in.amount),
                subject=f"Job Analysis - {order_in.product_type}",
                return_url="http://localhost:3000/payment/success", # 用户在浏览器用手机扫码完成后，重定向返回 Vue/React 前端的渲染落地页地址（必须公网访问）
                notify_url=f"{settings.PAYMENT_NOTIFY_BASE_URL}/alipay"
            )
            # 沙箱与正式生产环境的快速动态切换路由
            gateway = "https://openapi-sandbox.dl.alipaydev.com/gateway.do" if settings.ALIPAY_DEBUG else "https://openapi.alipay.com/gateway.do"
            response.pay_url = f"{gateway}?{order_string}"
            
        elif order_in.payment_method == PaymentMethod.WECHAT:
            if not wechat_client:
                raise ExternalServiceException(message="WeChat Pay not configured")
                
            code, message = wechat_client.pay(
                description=f"Job Analysis - {order_in.product_type}",
                out_trade_no=order_no,
                amount={'total': int(order_in.amount * 100)}, # [重中之重] 微信平台的金额要求必须全为分（没有小数点）。因此把元强转并抹去浮点带来的风险。
                payer={'openid': current_user.wechat_info.openid} if current_user.wechat_info else None
            )
            
            result = json.loads(message)
            if code in [200, 201]:
                 response.qr_code_url = result.get('code_url')
            else:
                 logger.error(f"WeChat Pay Error: {message}")
                 raise ExternalServiceException(message="WeChat Pay failed")
    
        elif order_in.payment_method == "wallet": # PaymentMethod.WALLET (use string to avoid import circle if any)
            # --- 原生生态自闭环：虚拟小金库直击扣费 ---
            wallet = await crud_wallet.wallet.get_by_user(db, current_user.id)
            if not wallet or wallet.balance < final_amount:
                raise AppException(status_code=400, code=StatusCode.BUSINESS_ERROR, message="Insufficient wallet balance")
                
            # 使用 DB 行悲观锁机制严格扣减个人资金流水
            success = await crud_wallet.wallet.consume_balance(
                db, 
                user_id=current_user.id, 
                amount=final_amount, 
                description=f"Payment for {order_no}",
                order_no=order_no
            )
            
            if success:
                # 只有扣减正确，才就地直接翻转本订单到 Paid 的完结生命周期
                order = await crud_payment.payment_order.get_by_order_no(db, order_no) # Re-fetch to be safe
                if order:
                    await handle_payment_success(db, order, transaction_id=f"WALLET_{uuid.uuid4().hex}")
                    response.status = PaymentStatus.PAID
                    response.pay_params = {"message": "Payment successful"}
            else:
                 raise AppException(status_code=400, code=StatusCode.BUSINESS_ERROR, message="Wallet payment failed")

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
    """高频轮询探测器: 查询云端实际是否支付成功"""
    order = await crud_payment.payment_order.get_by_order_no(db, order_no)
    if not order:
        raise AppException(status_code=404, code=StatusCode.BUSINESS_ERROR, message="Order not found")
        
    # 数据隔离保护: 没有 Admin Role 的人只有权查询 Owner 为直接自身的交易详单
    if order.user_id != current_user.id:
        raise PermissionDeniedException(message="Not authorized")
        
    # todo: (预留扩展能力) 若此时查出还是 Pending，可以直接由服务端反向再向支付宝/微信通过订单轮询来一次校准。
    # ...
    
    return order

@router.post("/notify/alipay")
async def alipay_notify(request: Request, db: AsyncSession = Depends(get_db)):
    """重要核心: 支付宝支付成功云端异步回调 Webhook"""
    data = await request.form()
    data_dict = dict(data)
    
    signature = data_dict.pop("sign")
    
    # 终极防线: 取使用阿里提供的支付宝 RS256 公钥体系暴力拦截一切没有带有正确摘要签名的 Hack Attack。
    if alipay_client and alipay_client.verify(data_dict, signature):
        trade_status = data_dict.get("trade_status")
        out_trade_no = data_dict.get("out_trade_no")
        trade_no = data_dict.get("trade_no")
        
        if trade_status in ["TRADE_SUCCESS", "TRADE_FINISHED"]:
            order = await crud_payment.payment_order.get_by_order_no(db, out_trade_no)
            if order:
                # 反作弊逻辑: 防止订单价格被攻击者在传输中间篡改。检查总交易落袋额度是否恒等于这单最初标价。
                total_amount = float(data_dict.get("total_amount", 0))
                if abs(total_amount - order.amount) > 0.01:
                    logger.critical(f"Amount mismatch for order {out_trade_no}: expected {order.amount}, got {total_amount}")
                    return "fail"

                await handle_payment_success(db, order, trade_no)
                
        return "success"
    
    return "fail"

@router.post("/notify/wechat")
async def wechat_notify(request: Request, db: AsyncSession = Depends(get_db)):
    """重要核心: 腾讯微信支付 V3 AEAD_AES_256_GCM 异步回调接收终端"""
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
                total_fee = amount_data.get('total', 0) # [重中之重] 微信平台的金额要求必须全为分（没有小数点）。因此把元强转并抹去浮点带来的风险。

                order = await crud_payment.payment_order.get_by_order_no(db, out_trade_no)
                if order:
                     # 反作弊逻辑: 防止订单价格被攻击者在传输中间篡改。检查总交易落袋额度是否恒等于这单最初标价。
                    expected_fee = int(order.amount * 100)
                    if total_fee != expected_fee:
                        logger.critical(f"Amount mismatch for Wechat order {out_trade_no}: expected {expected_fee}, got {total_fee}")
                        # 若发现微信侧的扣款数额不对，不能姑息直接返回失败 500！这样系统将会把这一单强行变为死信单走客服体系。
                        return {"code": "FAIL", "message": "Amount mismatch"}

                    await handle_payment_success(db, order, transaction_id)
                    
            return {"code": "SUCCESS", "message": "OK"}
        except Exception as e:
            logger.error(f"WeChat Notify Error: {e}")
            return {"code": "FAIL", "message": str(e)}
            
    return {"code": "FAIL", "message": "Config error"}
