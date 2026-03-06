<script setup>
import { useAiTaskStore } from "@/stores/aiTask";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";

const store = useAiTaskStore();
const router = useRouter();
const { taskList, pendingCount, hasUnread, panelOpen } = storeToRefs(store);

const statusIcon = (status) => {
  switch (status) {
    case "pending":
      return "⏳";
    case "processing":
      return "🔄";
    case "completed":
      return "✅";
    case "failed":
      return "❌";
    default:
      return "📋";
  }
};

const statusText = (status) => {
  switch (status) {
    case "pending":
      return "等待中";
    case "processing":
      return "处理中";
    case "completed":
      return "已完成";
    case "failed":
      return "失败";
    default:
      return status;
  }
};

const timeAgo = (dateStr) => {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  return `${Math.floor(hours / 24)}天前`;
};

const handleClick = async (task) => {
  store.markRead(task.taskId);
  store.togglePanel(); // Close panel on navigate

  if (task?.taskId) {
    await store.fetchTaskById(task.taskId, task.featureKey);
  }

  if (task.featureKey === "career_compass") {
    router.push({ path: "/career-compass", query: { task_id: task.taskId, feature_key: task.featureKey } });
  } else if (task.featureKey === "career_advice") {
    router.push({ path: "/major-analysis", query: { task_id: task.taskId, feature_key: task.featureKey } });
  } else if (task.featureKey === "resume_parse") {
    router.push({ path: "/my/resume", query: { task_id: task.taskId, feature_key: task.featureKey } });
  }
};
</script>

<template>
  <Transition name="panel-slide">
    <div v-if="panelOpen" class="ai-panel-overlay" @click.self="store.togglePanel">
      <div class="ai-panel">
        <div class="panel-header">
          <h3>
            <span class="header-icon">🤖</span>
            AI 任务中心
          </h3>
          <div class="header-actions">
            <button
              v-if="hasUnread"
              class="mark-all-btn"
              @click="store.markAllRead"
            >
              全部已读
            </button>
            <button class="close-btn" @click="store.togglePanel">✕</button>
          </div>
        </div>

        <div class="panel-body">
          <div v-if="taskList.length === 0" class="empty-state">
            <div class="empty-icon">📭</div>
            <p>暂无 AI 任务记录</p>
          </div>

          <div v-else class="task-list">
            <div
              v-for="task in taskList"
              :key="task.taskId"
              class="task-item"
              :class="{
                'is-pending': task.status === 'pending' || task.status === 'processing',
                'is-completed': task.status === 'completed',
                'is-failed': task.status === 'failed',
                'is-unread': !task.read && task.status !== 'pending' && task.status !== 'processing',
              }"
              @click="handleClick(task)"
            >
              <div class="task-icon">{{ statusIcon(task.status) }}</div>
              <div class="task-content">
                <div class="task-title">
                  {{ store.featureLabel(task.featureKey) }}
                  <span class="task-status" :class="task.status">
                    {{ statusText(task.status) }}
                  </span>
                </div>
                <div class="task-meta">
                  <span class="task-time">{{ timeAgo(task.createdAt) }}</span>
                  <span v-if="task.executionTime" class="task-duration">
                    耗时 {{ task.executionTime }}s
                  </span>
                </div>
                <div v-if="task.error" class="task-error">
                  {{ task.error }}
                </div>
              </div>
              <div v-if="!task.read && task.status !== 'pending' && task.status !== 'processing'" class="unread-dot"></div>
              <div v-if="task.status === 'pending' || task.status === 'processing'" class="spinner"></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.ai-panel-overlay {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 2000;
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(2px);
}

.ai-panel {
  position: absolute;
  top: 0;
  right: 0;
  width: 420px;
  max-width: 90vw;
  height: 100vh;
  background: #0f172a;
  border-left: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  box-shadow: -8px 0 30px rgba(0, 0, 0, 0.4);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.panel-header h3 {
  margin: 0;
  font-size: 1.1rem;
  color: #f1f5f9;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.header-icon {
  font-size: 1.3rem;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.mark-all-btn {
  background: transparent;
  border: 1px solid rgba(96, 165, 250, 0.3);
  color: #60a5fa;
  padding: 0.3rem 0.75rem;
  border-radius: 6px;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
}

.mark-all-btn:hover {
  background: rgba(96, 165, 250, 0.1);
  border-color: #60a5fa;
}

.close-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0.25rem;
  border-radius: 4px;
  transition: all 0.2s;
}

.close-btn:hover {
  color: #f1f5f9;
  background: rgba(255, 255, 255, 0.05);
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

.empty-state {
  text-align: center;
  padding: 4rem 2rem;
  color: #64748b;
}

.empty-icon {
  font-size: 3rem;
  margin-bottom: 1rem;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.task-item {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 1rem;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.05);
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}

.task-item:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.1);
}

.task-item.is-unread {
  border-left: 3px solid #3b82f6;
  background: rgba(59, 130, 246, 0.05);
}

.task-item.is-pending,
.task-item.is-pending {
  border-left: 3px solid #f59e0b;
  background: rgba(245, 158, 11, 0.03);
}

.task-icon {
  font-size: 1.3rem;
  flex-shrink: 0;
  margin-top: 2px;
}

.task-content {
  flex: 1;
  min-width: 0;
}

.task-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: #e2e8f0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.task-status {
  font-size: 0.75rem;
  font-weight: 500;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
}

.task-status.pending,
.task-status.processing {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
}

.task-status.completed {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
}

.task-status.failed {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
}

.task-meta {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.35rem;
  font-size: 0.8rem;
  color: #64748b;
}

.task-error {
  margin-top: 0.35rem;
  font-size: 0.82rem;
  color: #f87171;
  line-height: 1.4;
}

.unread-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #3b82f6;
  flex-shrink: 0;
  margin-top: 8px;
  box-shadow: 0 0 6px rgba(59, 130, 246, 0.4);
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(245, 158, 11, 0.2);
  border-top-color: #f59e0b;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  flex-shrink: 0;
  margin-top: 4px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* Slide transition */
.panel-slide-enter-active,
.panel-slide-leave-active {
  transition: all 0.3s ease;
}

.panel-slide-enter-active .ai-panel,
.panel-slide-leave-active .ai-panel {
  transition: transform 0.3s ease;
}

.panel-slide-enter-from,
.panel-slide-leave-to {
  opacity: 0;
}

.panel-slide-enter-from .ai-panel,
.panel-slide-leave-to .ai-panel {
  transform: translateX(100%);
}
</style>
