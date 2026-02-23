<script setup>
import { ref, computed } from 'vue';
import { useAuthStore } from '../stores/auth';

const props = defineProps(['isOpen']);
const emit = defineEmits(['close']);
const authStore = useAuthStore();

const activeTab = ref('account'); // 'scan' | 'phone' | 'account'
const phone = ref('');
const code = ref('');
const username = ref('');
const password = ref('');
const isRegister = ref(false);
const countdown = ref(0);
const isLoading = ref(false);
const errorMsg = ref('');
const scanStatus = ref('waiting'); // 'waiting' | 'scanned' | 'confirmed' | 'expired'

// QR Code Logic
const qrTicket = ref('');
const qrUrl = ref('');
const pollTimer = ref(null);

// Debug code holder
const debugCode = ref('');

const close = () => {
    stopPolling();
    emit('close');
    resetForm();
};

const resetForm = () => {
    phone.value = '';
    code.value = '';
    username.value = '';
    password.value = '';
    isRegister.value = false;
    errorMsg.value = '';
    debugCode.value = '';
    scanStatus.value = 'waiting';
    qrTicket.value = '';
    qrUrl.value = '';
};

// Start Polling Status
const startPolling = () => {
    stopPolling();
    pollTimer.value = setInterval(async () => {
        if (!qrTicket.value) return;
        try {
            const res = await authStore.checkQrCodeStatus(qrTicket.value);
            if (res.status === 'scanned') {
                scanStatus.value = 'scanned';
            } else if (res.status === 'confirmed') {
                scanStatus.value = 'confirmed';
                stopPolling();
                // Login Success!
                // The 'login_data' is nested in the response
                if (res.login_data) {
                     // Manually trigger success handling since we bypass the store's login action
                     authStore.token = res.login_data.token.access_token;
                     authStore.user = res.login_data.user;
                     localStorage.setItem('token', authStore.token);
                     localStorage.setItem('user', JSON.stringify(authStore.user));
                     close();
                }
            } else if (res.status === 'expired') {
                 stopPolling();
                 scanStatus.value = 'expired';
                 errorMsg.value = '二维码已过期，请刷新';
            }
        } catch (e) {
            console.error(e);
        }
    }, 2000);
};

const stopPolling = () => {
    if (pollTimer.value) clearInterval(pollTimer.value);
    pollTimer.value = null;
};

// Init QR on tab switch
import { watch } from 'vue';
watch(activeTab, async (newVal) => {
    if (newVal === 'scan') {
        try {
            isLoading.value = true;
            const res = await authStore.getQrCode();
            qrTicket.value = res.ticket;
            qrUrl.value = res.url;
            scanStatus.value = 'waiting';
            startPolling();
        } catch (e) {
            errorMsg.value = '获取二维码失败';
        } finally {
            isLoading.value = false;
        }
    } else {
        stopPolling();
    }
});

const sendCode = async () => {
    if (!phone.value || phone.value.length !== 11) {
        errorMsg.value = '请输入正确的手机号';
        return;
    }
    
    try {
        const res = await authStore.sendSmsCode(phone.value);
        if (res.debug_code) {
            debugCode.value = `测试验证码: ${res.debug_code}`;
        }
        
        countdown.value = 60;
        const timer = setInterval(() => {
            countdown.value--;
            if (countdown.value <= 0) clearInterval(timer);
        }, 1000);
        
        errorMsg.value = '';
    } catch (err) {
        errorMsg.value = err.response?.data?.detail || '发送失败，请重试';
    }
};

const handleLogin = async () => {
    isLoading.value = true;
    errorMsg.value = '';
    
    try {
        if (activeTab.value === 'phone') {
            if (!phone.value || !code.value) throw new Error('请输入手机号和验证码');
            await authStore.loginWithPhone(phone.value, code.value);
        } else if (activeTab.value === 'account') {
            if (!username.value || !password.value) throw new Error('请输入账号和密码');
            if (isRegister.value) {
                await authStore.register({ 
                    username: username.value, 
                    password: password.value,
                    nickname: username.value
                });
            } else {
                await authStore.login(username.value, password.value);
            }
        }
        close();
    } catch (err) {
        errorMsg.value = err.response?.data?.detail || err.message || '操作失败';
    } finally {
        isLoading.value = false;
    }
};

const simulateScan = async () => {
    scanStatus.value = 'scanned';
    
    // Check if authStore is available, if not, mock it locally or handle error
    try {
        // Simulate network delay
        setTimeout(async () => {
             // Mock login with wechat logic (since backend expects code)
             // In a real scan scenario, the backend would push a token to us via websocket/polling
             // Here we just call the existing mock login
             try {
                await authStore.loginWithWechat('MOBILE_SCAN_MOCK_CODE');
                close();
             } catch (e) {
                 errorMsg.value = '登录失败: ' + e.message;
                 scanStatus.value = 'waiting';
             }
        }, 1000);
    } catch (e) {
        console.error(e);
    }
};
</script>

<template>
  <div v-if="isOpen" class="modal-overlay" @click.self="close">
    <div class="modal-content">
        <button class="close-btn" @click="close">&times;</button>
        
        <div class="tabs">
            <button 
                :class="{ active: activeTab === 'account' }" 
                @click="activeTab = 'account'"
            >账号登录</button>
            <button 
                :class="{ active: activeTab === 'phone' }" 
                @click="activeTab = 'phone'"
            >短信登录</button>
            <button 
                :class="{ active: activeTab === 'scan' }" 
                @click="activeTab = 'scan'"
            >扫码登录</button>
        </div>
        
        <div class="tab-content">
            <!-- 账号登录/注册 -->
            <div v-if="activeTab === 'account'" class="account-login">
                <div class="input-group">
                    <input type="text" v-model="username" :placeholder="isRegister ? '预设用户名' : '用户名 / 邮箱 / 手机号'" />
                </div>
                <div class="input-group">
                    <input type="password" v-model="password" placeholder="密码" @keyup.enter="handleLogin" />
                </div>
                
                <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
                
                <button 
                    class="login-btn" 
                    :disabled="isLoading"
                    @click="handleLogin"
                >
                    {{ isLoading ? '提交中...' : (isRegister ? '立即注册' : '登录') }}
                </button>
                
                <div class="toggle-mode">
                    <span @click="isRegister = !isRegister">
                        {{ isRegister ? '已有账号？去登录' : '没有账号？立即注册' }}
                    </span>
                </div>
            </div>

            <!-- 扫码登录 -->
            <div v-if="activeTab === 'scan'" class="wechat-login">
                <div class="qr-container">
                    <div class="qr-placeholder" v-if="qrUrl">
                        <img :src="qrUrl" alt="Scan QR" />
                        
                        <!-- 覆盖层 -->
                        <div v-if="scanStatus === 'scanned'" class="scan-overlay">
                            <span class="check-icon">✓</span>
                            <p>扫描成功</p>
                            <p style="font-size: 0.8rem; color: #666">请在手机上确认</p>
                        </div>
                         <div v-if="scanStatus === 'expired'" class="scan-overlay" style="cursor: pointer" @click="activeTab = 'account'; setTimeout(()=>activeTab='scan', 0)">
                            <p style="color: #ef4444">已过期</p>
                            <p style="font-size: 0.8rem">点击刷新</p>
                        </div>
                    </div>
                </div>
                
                <p v-if="scanStatus === 'waiting'">请使用 <strong>APP</strong> 扫码登录</p>
                <p v-else-if="scanStatus === 'scanned'">已扫码，请在手机上点击确认</p>
                <p v-else-if="scanStatus === 'confirmed'">登录成功，正在跳转...</p>
                
                <div class="mock-actions">
                     <!-- 开发模式辅助按钮 -->
                    <button class="mock-btn" @click="simulateScan" v-if="scanStatus === 'waiting'" :disabled="!qrTicket">
                        (测试) 模拟手机扫码
                    </button>
                     <button class="mock-btn" @click="simulateConfirm" v-if="scanStatus === 'scanned'" style="margin-left: 10px">
                        (测试) 模拟手机确认
                    </button>
                </div>
                
                <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
            </div>
            
            <!-- 手机登录 -->
            <div v-if="activeTab === 'phone'" class="phone-login">
                <div class="input-group">
                    <input type="tel" v-model="phone" placeholder="请输入手机号" maxlength="11" />
                </div>
                
                <div class="input-group code-group">
                    <input type="text" v-model="code" placeholder="验证码" maxlength="6" />
                    <button 
                        class="send-btn" 
                        :disabled="countdown > 0" 
                        @click="sendCode"
                    >
                        {{ countdown > 0 ? `${countdown}s` : '获取验证码' }}
                    </button>
                </div>
                
                <div v-if="debugCode" class="debug-info">{{ debugCode }}</div>
                <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
                
                <button 
                    class="login-btn" 
                    :disabled="isLoading"
                    @click="handleLogin"
                >
                    {{ isLoading ? '登录中...' : '登录 / 注册' }}
                </button>
            </div>
        </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(5px);
    z-index: 2000;
    display: flex;
    justify-content: center;
    align-items: center;
}

.modal-content {
    background: var(--color-background-soft);
    border: 1px solid var(--color-border);
    border-radius: 1rem;
    width: 90%;
    max-width: 400px;
    padding: 2rem;
    position: relative;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
}

.close-btn {
    position: absolute;
    top: 1rem;
    right: 1rem;
    background: none;
    font-size: 1.5rem;
    color: var(--color-text-mute);
}

.tabs {
    display: flex;
    border-bottom: 2px solid var(--color-border);
    margin-bottom: 2rem;
}

.tabs button {
    flex: 1;
    background: none;
    padding: 1rem;
    font-size: 1rem;
    color: var(--color-text-mute);
    position: relative;
    transition: 0.3s;
}

.tabs button.active {
    color: var(--color-heading);
    font-weight: 600;
}

.tabs button.active::after {
    content: '';
    position: absolute;
    bottom: -2px;
    left: 0;
    width: 100%;
    height: 2px;
    background: var(--color-primary);
}

.wechat-login {
    text-align: center;
    padding: 1rem 0;
}

.qr-placeholder img {
    border-radius: 0.5rem;
    margin-bottom: 1rem;
    padding: 0.5rem;
    background: white;
}

.wechat-login p {
    color: var(--color-text-mute);
}

.input-group {
    margin-bottom: 1.25rem;
}

.input-group input {
    width: 100%;
    padding: 0.8rem 1rem;
    background: var(--color-background);
    border: 1px solid var(--color-border);
    border-radius: 0.5rem;
    color: var(--color-text);
    font-size: 1rem;
    outline: none;
    transition: 0.3s;
}

.input-group input:focus {
    border-color: var(--color-primary);
}

.code-group {
    display: flex;
    gap: 0.8rem;
}

.send-btn {
    width: 120px;
    background: var(--color-background-mute);
    color: var(--color-text);
    border-radius: 0.5rem;
    font-size: 0.9rem;
    transition: 0.3s;
}

.send-btn:hover:not(:disabled) {
    background: var(--color-border-hover);
}

.login-btn {
    width: 100%;
    padding: 0.8rem;
    background: linear-gradient(135deg, var(--color-primary), var(--color-secondary));
    color: white;
    font-weight: 600;
    border-radius: 0.5rem;
    margin-top: 1rem;
    transition: 0.3s;
}

.login-btn:hover:not(:disabled) {
    opacity: 0.9;
    transform: translateY(-1px);
}

.login-btn:disabled {
    opacity: 0.7;
    cursor: not-allowed;
}

.error-msg {
    color: #ef4444;
    font-size: 0.9rem;
    margin-bottom: 1rem;
    text-align: center;
}

.debug-info {
    color: #eab308;
    background: rgba(234, 179, 8, 0.1);
    font-size: 0.85rem;
    padding: 0.5rem;
    border-radius: 0.3rem;
    margin-bottom: 1rem;
    text-align: center;
}

.toggle-mode {
    margin-top: 1.5rem;
    text-align: center;
    font-size: 0.9rem;
    color: var(--color-text-mute);
}

.toggle-mode span {
    color: var(--color-primary);
    cursor: pointer;
    font-weight: 500;
}

.toggle-mode span:hover {
    text-decoration: underline;
}

.mock-actions {
    margin-top: 1rem;
}

.mock-btn {
    background: rgba(16, 185, 129, 0.1);
    color: #10b981;
    border: 1px dashed #10b981;
    padding: 0.5rem 1rem;
    border-radius: 0.5rem;
    font-size: 0.85rem;
    transition: 0.3s;
}

.mock-btn:hover {
    background: #10b981;
    color: white;
}

.qr-container {
    position: relative;
    display: inline-block;
}

.qr-placeholder {
    position: relative;
}

.scan-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(255, 255, 255, 0.9);
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    border-radius: 0.5rem;
}

.check-icon {
    font-size: 3rem;
    color: #10b981;
    font-weight: bold;
}

.scan-overlay p {
    color: #10b981;
    margin: 0;
    font-weight: 600;
}
</style>
