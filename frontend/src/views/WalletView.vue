<script setup>
import { ref, onMounted } from "vue";
import api from "../core/api";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const balance = ref(0);
const loading = ref(false);
const topUpAmount = ref(10);
const paymentModalOpen = ref(false);
const paymentQrCode = ref("");
const paymentOrderNo = ref("");
const paymentStatus = ref("pending"); // pending, paid
let checkInterval = null;

const quickAmounts = [10, 50, 100, 200];

const fetchBalance = async () => {
  try {
    const res = await api.get("/wallet/balance");
    balance.value = res.data.balance;
  } catch (e) {
    console.error("Failed to fetch balance", e);
  }
};

const handleTopUp = async () => {
  if (topUpAmount.value <= 0) return;

  loading.value = true;
  try {
    const res = await api.post("/payment/create", {
      amount: topUpAmount.value,
      product_type: "wallet_topup",
      payment_method: "alipay", // Default to alipay for now, or add selector
    });

    // Handle Alipay Gateway URL
    if (res.data.pay_url) {
      window.location.href = res.data.pay_url;
    } else if (res.data.qr_code_url) {
      // WeChat
      paymentQrCode.value = res.data.qr_code_url;
      paymentOrderNo.value = res.data.order_no;
      paymentModalOpen.value = true;
      pollStatus();
    }
  } catch (e) {
    console.error("Payment failed", e);
    alert("创建订单失败");
  } finally {
    loading.value = false;
  }
};

const pollStatus = () => {
  if (checkInterval) clearInterval(checkInterval);
  checkInterval = setInterval(async () => {
    try {
      const res = await api.get(`/payment/check/${paymentOrderNo.value}`);
      if (res.data.status === "paid") {
        paymentStatus.value = "paid";
        clearInterval(checkInterval);
        setTimeout(() => {
          closeModal();
          fetchBalance();
          alert("充值成功！");
        }, 1000);
      }
    } catch (e) {
      // ignore
    }
  }, 2000);
};

const closeModal = () => {
  paymentModalOpen.value = false;
  if (checkInterval) clearInterval(checkInterval);
  paymentStatus.value = "pending";
  paymentQrCode.value = "";
};

onMounted(() => {
  fetchBalance();
});
</script>

<template>
  <div class="wallet-view">
    <div class="balance-card">
      <h2>我的钱包</h2>
      <div class="balance-display">
        <span class="currency">¥</span>
        <span class="amount">{{ balance.toFixed(2) }}</span>
      </div>
      <p class="status">账户状态: 正常</p>
    </div>

    <div class="topup-card">
      <h3>余额充值</h3>
      <div class="amount-presets">
        <button
          v-for="amt in quickAmounts"
          :key="amt"
          :class="{ active: topUpAmount === amt }"
          @click="topUpAmount = amt"
        >
          ¥{{ amt }}
        </button>
      </div>
      <div class="input-group">
        <label>自定义金额</label>
        <input type="number" v-model="topUpAmount" min="0.01" step="0.01" />
      </div>

      <button class="pay-btn" @click="handleTopUp" :disabled="loading">
        {{ loading ? "处理中..." : "立即充值 (支付宝)" }}
      </button>
    </div>

    <!-- Payment Modal (Simple implementation) -->
    <div v-if="paymentModalOpen" class="modal-overlay">
      <div class="modal-content">
        <h3>扫码支付</h3>
        <div class="qr-code">
          <!-- Simulate QR Image for now if using URL, usually generate QR from URL string -->
          <p>请使用微信扫码</p>
          <p class="code-url">{{ paymentQrCode }}</p>
        </div>
        <button @click="closeModal">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wallet-view {
  max-width: 800px;
  margin: 0 auto;
  padding: 2rem;
}

.balance-card {
  background: linear-gradient(135deg, #38bdf8 0%, #3b82f6 100%);
  color: white;
  padding: 2rem;
  border-radius: 1rem;
  margin-bottom: 2rem;
  box-shadow: 0 10px 15px -3px rgba(59, 130, 246, 0.3);
}

.balance-display {
  font-size: 3rem;
  font-weight: bold;
  margin: 1rem 0;
}

.currency {
  font-size: 1.5rem;
  vertical-align: top;
  margin-right: 0.5rem;
}

.topup-card {
  background: #1e293b;
  padding: 2rem;
  border-radius: 1rem;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.amount-presets {
  display: flex;
  gap: 1rem;
  margin: 1.5rem 0;
}

.amount-presets button {
  flex: 1;
  padding: 1rem;
  background: #0f172a;
  border: 1px solid #334155;
  color: white;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 1.1rem;
}

.amount-presets button.active {
  border-color: #38bdf8;
  background: rgba(56, 189, 248, 0.1);
  color: #38bdf8;
}

.input-group {
  margin-bottom: 2rem;
}

.input-group label {
  display: block;
  margin-bottom: 0.5rem;
  color: #94a3b8;
}

.input-group input {
  width: 100%;
  padding: 0.8rem;
  background: #0f172a;
  border: 1px solid #334155;
  color: white;
  border-radius: 0.5rem;
  font-size: 1.2rem;
}

.pay-btn {
  width: 100%;
  padding: 1rem;
  background: #38bdf8;
  border: none;
  border-radius: 0.5rem;
  color: white;
  font-weight: bold;
  font-size: 1.2rem;
  cursor: pointer;
}
.pay-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}
.modal-content {
  background: #1e293b;
  padding: 2rem;
  border-radius: 1rem;
  text-align: center;
  color: white;
}
.code-url {
  word-break: break-all;
  background: #0f172a;
  padding: 1rem;
  margin: 1rem 0;
  font-family: monospace;
}
</style>
