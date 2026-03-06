<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { walletAPI } from "@/api/wallet";

const route = useRoute();
const PENDING_ORDER_KEY = "wallet_pending_order_no";

const loadingBalance = ref(false);
const loadingTopup = ref(false);
const loadingManualTopup = ref(false);
const loadingTransactions = ref(false);
const loadingOrders = ref(false);

const balance = ref(0);
const walletStatus = ref("active");

const topUpAmount = ref(10);
const paymentMethod = ref("alipay");
const quickAmounts = [10, 50, 100, 200];

const paymentModalOpen = ref(false);
const paymentOrderNo = ref("");
const paymentQrCodeUrl = ref("");
const paymentStatus = ref("pending");
const paymentFailureReason = ref("");

const txItems = ref([]);
const txTotal = ref(0);
const txPage = ref(1);
const txPageSize = ref(10);

const orderItems = ref([]);
const orderTotal = ref(0);
const orderPage = ref(1);
const orderPageSize = ref(10);
const orderStatusFilter = ref("");

let checkInterval = null;

const qrPreviewUrl = computed(() =>
  paymentQrCodeUrl.value
    ? `https://api.qrserver.com/v1/create-qr-code/?size=220x220&data=${encodeURIComponent(paymentQrCodeUrl.value)}`
    : "",
);
const txTotalPages = computed(() =>
  Math.max(1, Math.ceil((txTotal.value || 0) / txPageSize.value)),
);
const orderTotalPages = computed(() =>
  Math.max(1, Math.ceil((orderTotal.value || 0) / orderPageSize.value)),
);

const formatMoney = (value) => Number(value || 0).toFixed(2);
const formatDateTime = (value) =>
  value ? new Date(value).toLocaleString() : "-";

const typeLabel = (type) => {
  if (type === "deposit") return "Deposit";
  if (type === "consume") return "Consume";
  if (type === "refund") return "Refund";
  if (type === "withdraw") return "Withdraw";
  return type || "-";
};

const statusLabel = (status) => {
  if (status === "pending") return "Pending";
  if (status === "paid") return "Paid";
  if (status === "failed") return "Failed";
  if (status === "expired") return "Expired";
  if (status === "refunded") return "Refunded";
  return status || "-";
};

const stopPolling = () => {
  if (checkInterval) {
    clearInterval(checkInterval);
    checkInterval = null;
  }
};

const fetchBalance = async () => {
  loadingBalance.value = true;
  try {
    const res = await walletAPI.getBalance();
    balance.value = Number(res.data.balance || 0);
    walletStatus.value = res.data.status || "active";
  } catch (error) {
    ElMessage.error("Failed to load wallet balance");
  } finally {
    loadingBalance.value = false;
  }
};

const fetchTransactions = async (page = txPage.value) => {
  loadingTransactions.value = true;
  txPage.value = Math.max(1, page);
  try {
    const res = await walletAPI.getTransactionsPage({
      page: txPage.value,
      size: txPageSize.value,
    });
    txItems.value = Array.isArray(res.data.items) ? res.data.items : [];
    txTotal.value = Number(res.data.total || 0);
  } catch (error) {
    ElMessage.error("Failed to load transactions");
  } finally {
    loadingTransactions.value = false;
  }
};

const fetchMyOrders = async (page = orderPage.value) => {
  loadingOrders.value = true;
  orderPage.value = Math.max(1, page);
  try {
    const res = await walletAPI.getMyOrders({
      page: orderPage.value,
      size: orderPageSize.value,
      status: orderStatusFilter.value || undefined,
    });
    orderItems.value = Array.isArray(res.data.items) ? res.data.items : [];
    orderTotal.value = Number(res.data.total || 0);
  } catch (error) {
    ElMessage.error("Failed to load recharge orders");
  } finally {
    loadingOrders.value = false;
  }
};

const markPaidAndRefresh = async (successMsg = "Top-up successful") => {
  paymentStatus.value = "paid";
  paymentFailureReason.value = "";
  stopPolling();
  localStorage.removeItem(PENDING_ORDER_KEY);
  await Promise.all([fetchBalance(), fetchTransactions(1), fetchMyOrders(1)]);
  ElMessage.success(successMsg);
};

const checkPaymentStatusOnce = async (orderNo) => {
  const res = await walletAPI.checkPaymentStatus(orderNo);
  return res.data || {};
};

const startPollingStatus = (orderNo) => {
  stopPolling();
  checkInterval = setInterval(async () => {
    try {
      const data = await checkPaymentStatusOnce(orderNo);
      if (data.status === "paid") {
        await markPaidAndRefresh();
      } else if (data.status === "failed" || data.status === "expired") {
        paymentStatus.value = data.status;
        paymentFailureReason.value = data.failure_reason || "Order not paid";
        stopPolling();
        localStorage.removeItem(PENDING_ORDER_KEY);
        await fetchMyOrders(1);
        ElMessage.warning(paymentFailureReason.value);
      }
    } catch (error) {
      // keep polling on transient network errors
    }
  }, 3000);
};

const handleTopUp = async () => {
  const amount = Number(topUpAmount.value);
  if (!amount || amount <= 0) {
    ElMessage.warning("Please input a valid amount");
    return;
  }

  loadingTopup.value = true;
  paymentFailureReason.value = "";
  try {
    const res = await walletAPI.createPayment({
      amount,
      product_type: "wallet_topup",
      payment_method: paymentMethod.value,
    });

    const data = res.data || {};
    if (data.order_no) {
      paymentOrderNo.value = data.order_no;
      localStorage.setItem(PENDING_ORDER_KEY, data.order_no);
    }

    if (data.status === "failed") {
      paymentStatus.value = "failed";
      paymentFailureReason.value = data.pay_params?.reason || "Payment create failed";
      await fetchMyOrders(1);
      ElMessage.error(paymentFailureReason.value);
      return;
    }

    if (data.pay_url) {
      window.location.href = data.pay_url;
      return;
    }

    if (data.qr_code_url) {
      paymentQrCodeUrl.value = data.qr_code_url;
      paymentModalOpen.value = true;
      paymentStatus.value = "pending";
      startPollingStatus(data.order_no);
      return;
    }

    if (data.status === "paid") {
      await markPaidAndRefresh("Payment successful");
      return;
    }

    ElMessage.warning("Order created, but no payment link returned");
  } catch (error) {
    ElMessage.error("Failed to create top-up order");
  } finally {
    loadingTopup.value = false;
  }
};

const handleManualTopUp = async () => {
  const amount = Number(topUpAmount.value);
  if (!amount || amount <= 0) {
    ElMessage.warning("Please input a valid amount");
    return;
  }

  loadingManualTopup.value = true;
  try {
    await walletAPI.simulateTopup({ amount });
    await Promise.all([fetchBalance(), fetchTransactions(1), fetchMyOrders(1)]);
    ElMessage.success("Manual top-up completed");
  } catch (error) {
    ElMessage.error("Manual top-up failed");
  } finally {
    loadingManualTopup.value = false;
  }
};

const closePaymentModal = () => {
  paymentModalOpen.value = false;
  stopPolling();
};

const handleReturnFromGateway = async () => {
  const orderNoFromQuery = route.query.out_trade_no;
  const orderNo =
    (typeof orderNoFromQuery === "string" && orderNoFromQuery) ||
    localStorage.getItem(PENDING_ORDER_KEY);
  if (!orderNo) return;

  paymentOrderNo.value = orderNo;
  try {
    const data = await checkPaymentStatusOnce(orderNo);
    if (data.status === "paid") {
      await markPaidAndRefresh("Payment confirmed");
      return;
    }
    if (data.status === "pending") {
      startPollingStatus(orderNo);
      return;
    }
    if (data.status === "failed" || data.status === "expired") {
      paymentFailureReason.value = data.failure_reason || "Order not paid";
      localStorage.removeItem(PENDING_ORDER_KEY);
      ElMessage.warning(paymentFailureReason.value);
    }
  } catch (error) {
    // ignore and allow manual refresh
  }
};

const onSelectAmount = (amount) => {
  topUpAmount.value = amount;
};

onMounted(async () => {
  await Promise.all([fetchBalance(), fetchTransactions(1), fetchMyOrders(1)]);
  await handleReturnFromGateway();
});

onUnmounted(() => {
  stopPolling();
});
</script>

<template>
  <div class="wallet-view">
    <section class="balance-card">
      <p class="title">My Wallet</p>
      <div class="balance" v-loading="loadingBalance">
        <span class="currency">CNY</span>
        <span class="value">{{ formatMoney(balance) }}</span>
      </div>
      <p class="sub">Status: {{ walletStatus }}</p>
    </section>

    <section class="panel">
      <h3>Top-up</h3>
      <div class="preset-grid">
        <button
          v-for="amount in quickAmounts"
          :key="amount"
          :class="{ active: Number(topUpAmount) === amount }"
          @click="onSelectAmount(amount)"
        >
          {{ amount }}
        </button>
      </div>

      <div class="row">
        <label>Amount</label>
        <input v-model.number="topUpAmount" min="0.01" step="0.01" type="number" />
      </div>

      <div class="row">
        <label>Payment Method</label>
        <div class="methods">
          <label><input v-model="paymentMethod" type="radio" value="alipay" /> Alipay</label>
          <label><input v-model="paymentMethod" type="radio" value="wechat" /> WeChat</label>
          <label><input v-model="paymentMethod" type="radio" value="wallet" /> Wallet</label>
        </div>
      </div>

      <div class="action-row">
        <button class="primary" :disabled="loadingTopup" @click="handleTopUp">
          {{ loadingTopup ? "Creating order..." : "Pay now" }}
        </button>
        <button class="ghost" :disabled="loadingManualTopup" @click="handleManualTopUp">
          {{ loadingManualTopup ? "Processing..." : "Manual Top-up (Test)" }}
        </button>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h3>Wallet Transactions</h3>
        <button class="ghost" @click="fetchTransactions(1)">Refresh</button>
      </div>

      <div v-if="loadingTransactions" class="empty">Loading...</div>
      <div v-else-if="txItems.length === 0" class="empty">No transaction</div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>Type</th>
            <th>Description</th>
            <th>Amount</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="tx in txItems" :key="tx.id">
            <td>{{ typeLabel(tx.transaction_type) }}</td>
            <td>{{ tx.description || "-" }}</td>
            <td :class="tx.amount >= 0 ? 'plus' : 'minus'">
              {{ tx.amount >= 0 ? "+" : "" }}{{ formatMoney(tx.amount) }}
            </td>
            <td>{{ formatDateTime(tx.created_at) }}</td>
          </tr>
        </tbody>
      </table>

      <div class="pager">
        <button class="ghost" :disabled="txPage <= 1" @click="fetchTransactions(txPage - 1)">
          Prev
        </button>
        <span>{{ txPage }} / {{ txTotalPages }}</span>
        <button
          class="ghost"
          :disabled="txPage >= txTotalPages"
          @click="fetchTransactions(txPage + 1)"
        >
          Next
        </button>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h3>Recharge Orders</h3>
        <div class="filters">
          <select v-model="orderStatusFilter" @change="fetchMyOrders(1)">
            <option value="">All</option>
            <option value="pending">Pending</option>
            <option value="paid">Paid</option>
            <option value="failed">Failed</option>
            <option value="expired">Expired</option>
            <option value="refunded">Refunded</option>
          </select>
          <button class="ghost" @click="fetchMyOrders(1)">Refresh</button>
        </div>
      </div>

      <div v-if="loadingOrders" class="empty">Loading...</div>
      <div v-else-if="orderItems.length === 0" class="empty">No recharge record</div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>Order No</th>
            <th>Amount</th>
            <th>Method</th>
            <th>Status</th>
            <th>Failure Reason</th>
            <th>Created At</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="order in orderItems" :key="order.order_no">
            <td>{{ order.order_no }}</td>
            <td>{{ formatMoney(order.amount) }}</td>
            <td>{{ order.payment_method }}</td>
            <td>{{ statusLabel(order.status) }}</td>
            <td>{{ order.failure_reason || "-" }}</td>
            <td>{{ formatDateTime(order.created_at) }}</td>
          </tr>
        </tbody>
      </table>

      <div class="pager">
        <button class="ghost" :disabled="orderPage <= 1" @click="fetchMyOrders(orderPage - 1)">
          Prev
        </button>
        <span>{{ orderPage }} / {{ orderTotalPages }}</span>
        <button
          class="ghost"
          :disabled="orderPage >= orderTotalPages"
          @click="fetchMyOrders(orderPage + 1)"
        >
          Next
        </button>
      </div>
    </section>

    <div v-if="paymentModalOpen" class="modal-overlay">
      <div class="modal-content">
        <h3>Scan and Pay</h3>
        <p>Order No: {{ paymentOrderNo }}</p>
        <img v-if="qrPreviewUrl" :src="qrPreviewUrl" alt="payment-qr" class="qr-image" />
        <p v-if="paymentStatus === 'pending'">Waiting for payment...</p>
        <p v-if="paymentStatus === 'failed'" class="fail-text">
          {{ paymentFailureReason || "Payment failed" }}
        </p>
        <button class="ghost" @click="closePaymentModal">Close</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wallet-view {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
  display: grid;
  gap: 16px;
}

.balance-card {
  border-radius: 12px;
  padding: 18px;
  background: linear-gradient(135deg, #0f172a, #1d4ed8);
  color: #fff;
}

.title {
  margin: 0;
  opacity: 0.9;
}

.balance {
  margin-top: 8px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.currency {
  font-size: 18px;
  font-weight: 600;
}

.value {
  font-size: 36px;
  font-weight: 800;
}

.sub {
  margin: 4px 0 0;
  opacity: 0.85;
}

.panel {
  background: rgba(15, 23, 42, 0.82);
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 12px;
  padding: 16px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.panel h3 {
  margin: 0 0 10px;
}

.preset-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}

.preset-grid button {
  height: 36px;
}

.preset-grid button.active {
  border-color: #3b82f6;
}

.row {
  margin-bottom: 12px;
}

.row label {
  display: block;
  margin-bottom: 6px;
}

.row input,
select {
  height: 36px;
  border: 1px solid #334155;
  background: #111827;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 0 10px;
}

.methods {
  display: flex;
  gap: 16px;
}

.methods label {
  display: flex;
  align-items: center;
  gap: 6px;
}

.filters {
  display: flex;
  align-items: center;
  gap: 8px;
}

.primary,
.ghost {
  height: 36px;
  border-radius: 8px;
  border: 1px solid #334155;
  padding: 0 12px;
  cursor: pointer;
}

.action-row {
  display: flex;
  gap: 8px;
}

.primary {
  background: #2563eb;
  color: #fff;
  border-color: #2563eb;
}

.primary:disabled,
.ghost:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.ghost {
  background: #111827;
  color: #e2e8f0;
}

.table {
  width: 100%;
  border-collapse: collapse;
}

.table th,
.table td {
  padding: 8px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
  text-align: left;
  vertical-align: top;
}

.plus {
  color: #22c55e;
}

.minus {
  color: #f87171;
}

.empty {
  padding: 16px 0;
  color: #94a3b8;
}

.pager {
  margin-top: 10px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  width: 320px;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 16px;
  text-align: center;
}

.qr-image {
  width: 220px;
  height: 220px;
  margin: 10px auto;
}

.fail-text {
  color: #f87171;
}
</style>
