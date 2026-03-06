<script setup>
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { messageAPI } from '@/api/message';
import { useAiTaskStore } from '@/stores/aiTask';

const messages = ref([]);
const loading = ref(true);
const router = useRouter();
const aiTaskStore = useAiTaskStore();

const fetchMessages = async () => {
    try {
        const res = await messageAPI.getMessages();
        messages.value = res.data;
    } catch (e) {
        console.error(e);
    } finally {
        loading.value = false;
    }
};

const markAsRead = async (msg) => {
    if (msg.is_read) return;
    try {
        await messageAPI.markAsRead(msg.id);
        msg.is_read = true;
    } catch (e) {
        console.error(e);
    }
};

const parseActionParam = (param) => {
    if (!param) return null;
    if (typeof param === "object") return param;
    try {
        return JSON.parse(param);
    } catch (e) {
        return null;
    }
};

const routeForFeature = (featureKey) => {
    if (featureKey === "career_compass") return "/career-compass";
    if (featureKey === "career_advice") return "/major-analysis";
    if (featureKey === "resume_parse") return "/my/resume";
    return null;
};

const handleMessageClick = async (msg) => {
    await markAsRead(msg);
    const action = parseActionParam(msg.action_param);
    if (action?.task_id) {
        await aiTaskStore.fetchTaskById(action.task_id, action.feature_key);
        const target = routeForFeature(action.feature_key);
        if (target) {
            router.push({ path: target, query: { task_id: action.task_id, feature_key: action.feature_key } });
        }
    }
};

const markAllRead = async () => {
    try {
        await messageAPI.markAllAsRead();
        messages.value.forEach(m => m.is_read = true);
    } catch (e) {
        console.error(e);
    }
};

const formatDate = (dateStr) => {
    return new Date(dateStr).toLocaleString();
};

onMounted(fetchMessages);
</script>

<template>
    <div class="msg-container">
        <div class="header">
             <h1>消息中心</h1>
             <button v-if="messages.some(m => !m.is_read)" @click="markAllRead" class="mark-all-btn">
                全部已读
             </button>
        </div>
       
        <div v-if="loading" class="loading">加载中...</div>
        <div v-else-if="messages.length === 0" class="empty">
            暂无消息
        </div>
        <div v-else class="list">
            <div 
                v-for="msg in messages" 
                :key="msg.id" 
                class="msg-card" 
                :class="{ 'unread': !msg.is_read }"
                @click="handleMessageClick(msg)"
            >
                <div class="icon-col">
                    <div class="icon" :class="msg.type">
                        {{ msg.type === 'system' ? '🔔' : '💬' }}
                    </div>
                </div>
                <div class="content-col">
                    <div class="msg-header">
                        <span class="title">{{ msg.title || (msg.type === 'system' ? '系统通知' : '新消息') }}</span>
                        <span class="date">{{ formatDate(msg.created_at) }}</span>
                    </div>
                    <div class="body">{{ msg.content }}</div>
                </div>
                <div v-if="!msg.is_read" class="dot"></div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.msg-container {
    max-width: 800px;
    margin: 2rem auto;
    padding: 0 1rem;
}

.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
}

.mark-all-btn {
    background: transparent;
    border: 1px solid var(--color-border);
    padding: 0.4rem 1rem;
    border-radius: 4px;
    cursor: pointer;
    color: var(--color-text-mute);
}
.mark-all-btn:hover {
    color: var(--color-primary);
    border-color: var(--color-primary);
}

.empty {
    text-align: center;
    color: var(--color-text-mute);
    padding: 4rem;
}

.list {
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.msg-card {
    background: var(--color-background-soft);
    border: 1px solid var(--color-border);
    border-radius: 8px;
    padding: 1.5rem;
    display: flex;
    gap: 1rem;
    cursor: pointer;
    position: relative;
    transition: 0.2s;
}

.msg-card:hover {
    border-color: var(--color-primary);
}

.msg-card.unread {
    background: var(--color-background-mute); /* Slighly highlighted or different shade */
    border-left: 4px solid var(--color-primary);
}

.icon {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: var(--color-background);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.2rem;
}
.icon.system { background: #fee2e2; color: #ef4444; }
.icon.user { background: #dbeafe; color: #3b82f6; }

.content-col { flex: 1; }

.msg-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 0.5rem;
}

.title { font-weight: bold; }
.date { font-size: 0.8rem; color: var(--color-text-mute); }

.body {
    color: var(--color-text-mute);
    font-size: 0.95rem;
    line-height: 1.5;
}

.dot {
    position: absolute;
    top: 1rem;
    right: 1rem;
    width: 8px;
    height: 8px;
    background: #ef4444;
    border-radius: 50%;
}
</style>
