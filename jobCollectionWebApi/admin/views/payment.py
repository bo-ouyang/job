import uuid
from datetime import datetime

from starlette_admin import TextAreaField, StringField, action, row_action

from common.databases.PostgresManager import db_manager
from common.databases.models.payment import PaymentOrder, PaymentStatus
from common.databases.models.wallet import TransactionType, UserWallet
from crud import wallet as crud_wallet

from .base import AdminRestrictedView


class PaymentOrderView(AdminRestrictedView):
    label = "支付订单"
    icon = "fa fa-credit-card"
    fields = [
        PaymentOrder.id,
        PaymentOrder.order_no,
        PaymentOrder.user,
        PaymentOrder.amount,
        PaymentOrder.payment_method,
        PaymentOrder.status,
        PaymentOrder.product_type,
        PaymentOrder.transaction_id,
        PaymentOrder.created_at,
        PaymentOrder.paid_at,
    ]
    search_builder = True
    can_create = False
    can_edit = False

    @row_action(
        name="manual_repair_order",
        text="手动补单",
        confirmation="确认将该订单标记为已支付并执行发货(充值)逻辑？",
        icon_class="fas fa-wrench",
        action_btn_class="btn-warning",
        submit_btn_text="确认补单",
        submit_btn_class="btn-warning",
    )
    async def manual_repair_order(self, request, pk):
        async with db_manager.async_session() as session:
            order = await session.get(PaymentOrder, int(pk))
            if not order:
                return "订单不存在"

            status = str(order.status)
            if status == PaymentStatus.PAID.value:
                return "该订单已支付，无需补单"
            if status == PaymentStatus.REFUNDED.value:
                return "已退款订单不允许补单"

            order.status = PaymentStatus.PAID
            order.paid_at = datetime.now()
            order.transaction_id = f"ADMIN_REPAIR_{uuid.uuid4().hex[:20].upper()}"

            extra = dict(order.extra_data or {})
            extra.pop("failure_reason", None)
            extra["manual_repair"] = {
                "admin": getattr(getattr(request.state, "user_obj", None), "username", "unknown"),
                "at": datetime.now().isoformat(),
            }
            order.extra_data = extra

            product_code = ""
            if isinstance(order.product_snapshot, dict):
                product_code = str(order.product_snapshot.get("code", ""))
            is_wallet_topup = bool(
                product_code.startswith("wallet_topup") or (order.product_type == "wallet_topup")
            )
            if is_wallet_topup:
                await crud_wallet.wallet.add_balance(
                    session,
                    user_id=order.user_id,
                    amount=order.amount,
                    source=f"admin_manual_repair:{order.order_no}",
                    order_no=order.order_no,
                    transaction_type=TransactionType.DEPOSIT,
                )

            session.add(order)
            await session.commit()
            await self._log_action(request, "MANUAL_REPAIR", order, f"Manual repaired order {order.order_no}")
            return f"补单成功: {order.order_no}"


class WalletAdminView(AdminRestrictedView):
    label = "钱包管理"
    icon = "fa fa-wallet"
    fields = [
        UserWallet.id,
        UserWallet.user,
        UserWallet.balance,
        UserWallet.frozen_balance,
        UserWallet.status,
        UserWallet.updated_at,
        UserWallet.created_at,
    ]
    search_builder = True
    can_create = False
    can_edit = False

    @action(
        name="manual_topup_wallet",
        text="手动充值",
        confirmation="给选中的钱包执行手动充值",
        submit_btn_text="确认充值",
        submit_btn_class="btn-success",
        form=[
            StringField(
                "amount",
                label="充值金额",
                help_text="正数，最多两位小数。例如 10.50",
            ),
            TextAreaField(
                "remark",
                label="备注",
                help_text="可选，写入流水备注",
                rows=2,
            ),
        ],
    )
    async def manual_topup_wallet(self, request, pks):
        if not pks:
            return "请先勾选至少一个钱包"

        data = await request.form()
        amount_raw = (data.get("amount") or "").strip()
        remark = (data.get("remark") or "").strip()
        try:
            amount = float(amount_raw)
        except Exception:
            return "金额格式错误"

        if amount <= 0:
            return "充值金额必须大于 0"

        admin_name = getattr(getattr(request.state, "user_obj", None), "username", "admin")
        success_count = 0

        async with db_manager.async_session() as session:
            for pk in pks:
                wallet = await session.get(UserWallet, int(pk))
                if not wallet:
                    continue
                source = f"admin_manual_topup by {admin_name}"
                if remark:
                    source = f"{source}: {remark}"
                await crud_wallet.wallet.add_balance(
                    session,
                    user_id=wallet.user_id,
                    amount=amount,
                    source=source,
                    transaction_type=TransactionType.DEPOSIT,
                )
                success_count += 1
            await session.commit()

        if success_count == 0:
            return "未找到可充值的钱包"
        return f"充值成功: {success_count} 个钱包，每个 +{amount:.2f}"
