<script setup>
import { ref, onMounted, reactive } from "vue";
import { useResumeStore } from "../stores/resume";
import { storeToRefs } from "pinia";

const store = useResumeStore();
const { resume, isLoading } = storeToRefs(store);

// UI States
const isEditingBasic = ref(false);
const showEduForm = ref(false);
const showWorkForm = ref(false);

const basicForm = reactive({});
const eduForm = reactive({});
const workForm = reactive({});

onMounted(async () => {
  await store.fetchMyResume();
});

// --- Basic Info ---
const startEditBasic = () => {
  if (resume.value) {
    Object.assign(basicForm, resume.value);
  } else {
    // Init empty
    Object.assign(basicForm, { name: "", email: "", phone: "" });
  }
  isEditingBasic.value = true;
};

const saveBasic = async () => {
  try {
    if (resume.value) {
      await store.updateResume(basicForm);
    } else {
      await store.createResume(basicForm);
    }
    isEditingBasic.value = false;
  } catch (e) {
    alert(e);
  }
};

const handleAvatarUpload = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const res = await store.uploadFile(file);
    // Update form or resume directly if supported?
    // We usually need to save the URL to the resume.
    // If we are editing, update form. If viewing, might need to trigger save.
    if (isEditingBasic.value) {
      basicForm.avatar = res.url;
    } else {
      // If not editing, we must be in view mode, but usually avatar upload is part of edit.
      // Let's assume user must click edit basics to upload avatar.
      // Or we support direct upload. For now, let's auto-save if resume exists.
      if (resume.value) {
        await store.updateResume({ avatar: res.url });
      }
    }
  } catch (e) {
    alert("上传失败");
  }
};

const handleResumeUpload = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const res = await store.uploadFile(file);
    if (resume.value) {
      await store.updateResume({ attachment_url: res.url });
    } else {
      // If no resume, create one? Or just alert they need basic info first?
      alert("请先填写并保存基本信息");
    }
  } catch (e) {
    alert("上传失败");
  }
};

// AI Parsing
const parsingStatus = ref("");
import { aiAPI } from '@/api/ai';

const handleSmartParse = async (event) => {
  const file = event.target.files[0];
  if (!file) return;

  parsingStatus.value = "uploading";
  const formData = new FormData();
  formData.append("file", file);

  try {
    await aiAPI.parseResume(formData);
    parsingStatus.value = "parsing";
  } catch (e) {
    if (e.response?.status === 409 || e.response?.data?.code === 40902) {
      parsingStatus.value = "";
      alert("当前有简历解析任务正在执行中，请等待完成后再试");
    } else if (e.code === "ECONNABORTED") {
      parsingStatus.value = "timeout";
      alert("请求超时，解析将在后台继续，请留意消息通知");
    } else {
      parsingStatus.value = "error";
      alert(e);
    }
  }
  // reset input
  event.target.value = "";
};

onMounted(() => {
  window.addEventListener("ws-message", onWsMessage);
});
import { onUnmounted } from "vue";
onUnmounted(() => {
  window.removeEventListener("ws-message", onWsMessage);
});

const onWsMessage = async (e) => {
  const msg = e.detail;
  if (msg.type === "resume_parsed") {
    const data = msg.data;
    parsingStatus.value = "success";

    // Auto fill Basic Info locally for display
    if (data.name) basicForm.name = data.name;
    if (data.phone) basicForm.phone = data.phone;
    if (data.email) basicForm.email = data.email;
    if (data.summary) basicForm.summary = data.summary;
    if (data.age) basicForm.age = data.age;
    if (data.gender) basicForm.gender = data.gender;
    if (data.desired_position)
      basicForm.desired_position = data.desired_position;

    // --- Smart Auto-Create Logic ---
    if (!resume.value) {
      console.log("No existing resume. Creating base resume first...");
      try {
        // 1. Create Base Resume
        await store.createResume(basicForm);
        // 2. Refresh store to get the ID (store.createResume usually updates state, but good to be sure)
        // store.createResume updates 'resume.value'
      } catch (err) {
        console.error("Failed to auto-create base resume:", err);
        alert("自动创建简历失败，请检查基本信息格式");
        return; // Stop if base creation failed
      }
    } else {
      // If resume exists, we might want to update it?
      // Let's just update the form and let user save, OR auto-save basics too?
      // User expectation: "Auto fill". If I just fill form, they need to click save.
      // But for consistency with "Smart Create", let's auto-save basics too if we are confident.
      // For now, let's update form and trigger edit mode (existing logic),
      // BUT we rely on `resume.value` for IDs for sub-items.
      // So safe to proceed to sub-items.
    }

    // Trigger edit mode to show the (now saved or updated) data
    isEditingBasic.value = true;

    // Auto-add Educations
    if (data.educations && Array.isArray(data.educations)) {
      for (const edu of data.educations) {
        // Determine if we should add?
        // For simplicity, let's add them via store (which saves to DB).
        try {
          await store.addEducation(edu);
        } catch (e) {
          console.error("Add edu failed", e);
        }
      }
    }

    // Auto-add Work Experiences
    if (data.work_experiences && Array.isArray(data.work_experiences)) {
      console.log("Start adding work experiences:", data.work_experiences);
      for (const work of data.work_experiences) {
        try {
          // Clean up empty strings for optional fields if needed, or rely on backend
          if (work.department === "") delete work.department;
          await store.addWorkExperience(work);
          console.log("Added work:", work.company);
        } catch (err) {
          console.error("Failed to add work experience:", work, err);
        }
      }
    }

    // Final refresh to ensure all items are displayed correctly
    await store.fetchMyResume();
    // Clear status after 3 seconds
    setTimeout(() => {
      parsingStatus.value = "";
    }, 3000);
  } else if (msg.type === "resume_parse_error") {
    parsingStatus.value = "error";
    alert(msg.message);
  }
};

// --- Education ---
const saveEdu = async () => {
  try {
    await store.addEducation(eduForm);
    showEduForm.value = false;
    Object.keys(eduForm).forEach((k) => (eduForm[k] = undefined)); // reset
  } catch (e) {
    alert(e);
  }
};

const removeEdu = async (id) => {
  if (confirm("确定删除?")) await store.deleteEducation(id);
};

// --- Work Experience ---
const saveWork = async () => {
  try {
    await store.addWorkExperience(workForm);
    showWorkForm.value = false;
    Object.keys(workForm).forEach((k) => (workForm[k] = undefined)); // reset
  } catch (e) {
    alert(e);
  }
};

const removeWork = async (id) => {
  if (confirm("确定删除?")) await store.deleteWorkExperience(id);
};
</script>

<template>
  <div class="resume-view">
    <div v-if="isLoading && !resume" class="loading">加载中...</div>

    <div v-else class="content">
      <!-- Header / Basic Info -->
      <div class="section basic-section">
        <div class="section-header">
          <h2>我的简历</h2>
          <button
            v-if="!isEditingBasic"
            @click="startEditBasic"
            class="btn-primary"
          >
            编辑基本信息
          </button>
          <div v-else class="edit-actions">
            <button @click="saveBasic" class="btn-primary">保存</button>
            <button @click="isEditingBasic = false" class="btn-outline">
              取消
            </button>
          </div>
        </div>

        <div v-if="!resume && !isEditingBasic" class="empty-resume">
          <div class="empty-icon">📄</div>
          <p>您还没有创建简历，完善简历能够大幅提高求职成功率</p>
          <div class="empty-actions">
            <button @click="startEditBasic" class="btn-outline big-btn">
              手动创建
            </button>
            <label
              class="btn-primary big-btn ai-upload-btn"
              :class="{ 'is-loading': parsingStatus }"
            >
              <span v-if="!parsingStatus">✨ 上传 PDF 智能生成</span>
              <span v-else-if="parsingStatus === 'uploading'"
                >🚀 正在上传...</span
              >
              <span v-else-if="parsingStatus === 'parsing'"
                >🧠 AI 深度解析中...</span
              >
              <span v-else-if="parsingStatus === 'success'">✅ 解析成功！</span>
              <input
                type="file"
                @change="handleSmartParse"
                accept=".pdf"
                hidden
                :disabled="!!parsingStatus"
              />
            </label>
          </div>
        </div>

        <div v-else-if="isEditingBasic" class="form-grid">
          <div class="form-group full-width">
            <label>头像</label>
            <div class="avatar-upload">
              <img
                v-if="basicForm.avatar"
                :src="basicForm.avatar"
                class="avatar-preview"
              />
              <input
                type="file"
                @change="handleAvatarUpload"
                accept="image/*"
              />
            </div>
          </div>
          <div class="form-group">
            <label>姓名</label>
            <input v-model="basicForm.name" />
          </div>
          <div class="form-group">
            <label>职位</label>
            <input
              v-model="basicForm.desired_position"
              placeholder="期望职位"
            />
          </div>
          <div class="form-group">
            <label>电话</label>
            <input v-model="basicForm.phone" />
          </div>
          <div class="form-group">
            <label>邮箱</label>
            <input v-model="basicForm.email" />
          </div>
          <div class="form-group">
            <label>年龄</label>
            <input v-model="basicForm.age" type="number" />
          </div>
          <div class="form-group">
            <label>性别</label>
            <select v-model="basicForm.gender">
              <option value="男">男</option>
              <option value="女">女</option>
            </select>
          </div>
          <div class="form-group full-width">
            <label>个人优势</label>
            <textarea v-model="basicForm.summary" rows="4"></textarea>
          </div>
        </div>

        <div v-else class="info-display">
          <div class="info-header">
            <div class="main-info">
              <h1 class="name">{{ resume.name }}</h1>
              <p class="summary">
                {{ resume.desired_position }} | {{ resume.gender }} |
                {{ resume.age }}岁
              </p>
              <div class="contact">
                <span>📞 {{ resume.phone }}</span>
                <span>✉️ {{ resume.email }}</span>
              </div>
            </div>
            <img
              :src="resume.avatar || '/default-avatar.png'"
              class="avatar-display"
            />
          </div>
          <div class="summary-text" v-if="resume.summary">
            <h3>个人优势</h3>
            <p>{{ resume.summary }}</p>
          </div>

          <div class="ai-action-area">
            <div class="ai-box">
              <h3><span class="ai-sparkle">✨</span> AI 智能简历解析</h3>
              <p>
                如果您有现成的 PDF
                简历，直接上传即可自动提取并结构化填入下方表单，准确率达 98%。
              </p>
              <label
                class="btn-primary ai-upload-btn"
                :class="{ 'is-loading': parsingStatus }"
              >
                <span v-if="!parsingStatus">上传并解析 PDF</span>
                <span v-else-if="parsingStatus === 'uploading'"
                  >🚀 正在上传...</span
                >
                <span v-else-if="parsingStatus === 'parsing'"
                  >🧠 AI 深度解析中...</span
                >
                <span v-else-if="parsingStatus === 'success'"
                  >✅ 解析成功，数据已更新</span
                >
                <input
                  type="file"
                  @change="handleSmartParse"
                  accept=".pdf"
                  hidden
                  :disabled="!!parsingStatus"
                />
              </label>
              <div class="parsing-progress" v-if="parsingStatus === 'parsing'">
                <div class="progress-bar">
                  <div class="progress-fill"></div>
                </div>
                <small>这可能需要 5-15 秒，请不要关闭页面</small>
              </div>
            </div>
          </div>

          <div class="attachment-area">
            <h3>附件简历</h3>
            <div v-if="resume.attachment_url" class="file-link">
              <a :href="resume.attachment_url" target="_blank"
                >📄 查看附件简历</a
              >
              <label class="btn-link">
                更新
                <input
                  type="file"
                  @change="handleResumeUpload"
                  accept=".pdf,.doc,.docx"
                  hidden
                />
              </label>
            </div>
            <div v-else>
              <label class="btn-primary">
                上传附件简历
                <input
                  type="file"
                  @change="handleResumeUpload"
                  accept=".pdf,.doc,.docx"
                  hidden
                />
              </label>
            </div>
          </div>
        </div>
      </div>

      <!-- Education -->
      <div class="section" v-if="resume">
        <div class="section-header">
          <h3>教育经历</h3>
          <button
            @click="showEduForm = true"
            v-if="!showEduForm"
            class="btn-text"
          >
            + 添加
          </button>
        </div>

        <div v-if="showEduForm" class="sub-form">
          <div class="form-group">
            <input v-model="eduForm.school" placeholder="学校" />
          </div>
          <div class="form-group">
            <input v-model="eduForm.major" placeholder="专业" />
          </div>
          <div class="form-group">
            <input v-model="eduForm.degree" placeholder="学历" />
          </div>
          <div class="form-group">
            <label>时间段</label>
            <div style="display: flex; gap: 10px; align-items: center">
              <input v-model="eduForm.start_date" type="date" />
              <span>至</span>
              <input v-model="eduForm.end_date" type="date" />
            </div>
          </div>
          <div class="form-actions">
            <button @click="saveEdu" class="btn-primary small">保存</button>
            <button @click="showEduForm = false" class="btn-outline small">
              取消
            </button>
          </div>
        </div>

        <div class="item-list">
          <div v-for="edu in resume.educations" :key="edu.id" class="item-card">
            <div class="item-main">
              <h4><span class="label-text">学校：</span>{{ edu.school }}</h4>
              <p>
                <span class="label-text">专业：</span>{{ edu.major }}
                <span class="separator">|</span>
                <span class="label-text">学历：</span>{{ edu.degree }}
              </p>
              <span class="item-date"
                ><span class="label-text">时间：</span>{{ edu.start_date }} 至
                {{ edu.end_date }}</span
              >
            </div>
            <button class="btn-danger small" @click="removeEdu(edu.id)">
              删除
            </button>
          </div>
        </div>
      </div>

      <!-- Work Experience -->
      <div class="section" v-if="resume">
        <div class="section-header">
          <h3>工作经历</h3>
          <button
            @click="showWorkForm = true"
            v-if="!showWorkForm"
            class="btn-text"
          >
            + 添加
          </button>
        </div>

        <div v-if="showWorkForm" class="sub-form">
          <div class="form-group">
            <input v-model="workForm.company" placeholder="公司名称" />
          </div>
          <div class="form-group">
            <input v-model="workForm.position" placeholder="职位" />
          </div>
          <div class="form-group">
            <input v-model="workForm.department" placeholder="部门 (可选)" />
          </div>
          <div class="form-group">
            <textarea
              v-model="workForm.content"
              placeholder="工作内容"
              rows="3"
            ></textarea>
          </div>
          <div class="form-group">
            <label>时间段</label>
            <div style="display: flex; gap: 10px">
              <input v-model="workForm.start_date" type="date" />
              <span>-</span>
              <input v-model="workForm.end_date" type="date" />
            </div>
          </div>
          <div class="form-actions">
            <button @click="saveWork" class="btn-primary small">保存</button>
            <button @click="showWorkForm = false" class="btn-outline small">
              取消
            </button>
          </div>
        </div>

        <div class="item-list">
          <div
            v-for="work in resume.work_experiences"
            :key="work.id"
            class="item-card"
          >
            <div class="item-main">
              <h4><span class="label-text">公司：</span>{{ work.company }}</h4>
              <p>
                <span class="label-text">职位：</span>{{ work.position }}
                <span v-if="work.department"
                  ><span class="separator">|</span>
                  <span class="label-text">部门：</span
                  >{{ work.department }}</span
                >
              </p>
              <span class="item-date"
                ><span class="label-text">时间：</span>{{ work.start_date }} 至
                {{ work.end_date || "至今" }}</span
              >
              <p v-if="work.content" class="item-desc">
                <span class="label-text">工作内容：</span>{{ work.content }}
              </p>
            </div>
            <button class="btn-danger small" @click="removeWork(work.id)">
              删除
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.resume-view {
  max-width: 900px;
  margin: 0 auto;
  padding: 2rem;
  color: #e2e8f0;
}

/* Dark Theme Variables */
.section {
  background: #1e293b; /* Slate-800 */
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
  box-shadow:
    0 4px 6px -1px rgba(0, 0, 0, 0.3),
    0 2px 4px -1px rgba(0, 0, 0, 0.15);
  border: 1px solid #334155;
  transition: all 0.3s;
}
.section:hover {
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.4);
  border-color: #475569;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
  border-bottom: 1px solid #334155;
  padding-bottom: 1rem;
}
.section-header h2,
.section-header h3 {
  font-size: 1.25rem;
  color: #f1f5f9;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.section-header h3::before {
  content: "";
  display: block;
  width: 6px;
  height: 24px;
  background: #60a5fa;
  border-radius: 3px;
}

/* Form Styles - Dark */
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}
.full-width {
  grid-column: span 2;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.form-group label {
  color: #94a3b8;
  font-size: 0.9rem;
  font-weight: 500;
}
input,
select,
textarea {
  padding: 0.75rem;
  border: 1px solid #475569;
  border-radius: 6px;
  background: #0f172a;
  color: #f8fafc;
  font-size: 0.95rem;
  transition: border-color 0.2s;
}
input:focus,
select:focus,
textarea:focus {
  border-color: #60a5fa;
  outline: none;
  box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.2);
}

/* Sub Form */
.sub-form {
  background: #1e293b;
  padding: 1.5rem;
  border-radius: 8px;
  border: 1px dashed #475569;
  margin-bottom: 1.5rem;
}

/* Timeline Items - Dark */
.item-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  position: relative;
  padding-left: 1rem;
}
.item-list::before {
  content: "";
  position: absolute;
  left: 0;
  top: 1rem;
  bottom: 1rem;
  width: 2px;
  background: #334155;
}

.item-card {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 1rem;
  border: 1px solid #334155;
  border-radius: 8px;
  background: #1e293b;
  position: relative;
  transition: transform 0.2s;
}
.item-card:hover {
  transform: translateX(5px);
  border-color: #475569;
  background: #263346;
}
.item-card::before {
  content: "";
  position: absolute;
  left: -1.35rem;
  top: 1.5rem;
  width: 10px;
  height: 10px;
  background: #3b82f6;
  border-radius: 50%;
  border: 2px solid #1e293b;
  box-shadow: 0 0 0 2px #60a5fa;
}

.item-main h4 {
  margin: 0 0 0.25rem 0;
  font-size: 1.1rem;
  color: #f1f5f9;
}
.item-main p {
  margin: 0 0 0.5rem 0;
  font-size: 0.95rem;
  color: #cbd5e1;
}
.item-date {
  display: inline-block;
  font-size: 0.85rem;
  color: #94a3b8;
  background: #1e293b;
  padding: 2px 0;
  border-radius: 4px;
}
.item-desc {
  margin-top: 0.5rem;
  font-size: 0.9rem;
  color: #cbd5e1;
  line-height: 1.6;
  white-space: pre-wrap;
}

/* Labels */
.label-text {
  font-weight: normal;
  color: #64748b;
  font-size: 0.9em;
  margin-right: 4px;
}
.separator {
  margin: 0 8px;
  color: #475569;
}

/* Buttons */
.btn-primary {
  background: #3b82f6;
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.2s;
}
.btn-primary:hover {
  background: #2563eb;
}
.btn-outline {
  background: transparent;
  border: 1px solid #475569;
  padding: 0.5rem 1rem;
  border-radius: 4px;
  cursor: pointer;
  color: #cbd5e1;
}
.btn-outline:hover {
  border-color: #94a3b8;
  color: #fff;
}
.btn-text {
  background: none;
  border: none;
  color: #60a5fa;
  cursor: pointer;
}
.btn-danger {
  background: #450a0a;
  color: #fca5a5;
  border: 1px solid #7f1d1d;
  padding: 0.3rem 0.8rem;
  border-radius: 4px;
  cursor: pointer;
}
.btn-success {
  background: #059669;
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.2s;
  display: inline-block;
  text-align: center;
}
.btn-success:hover {
  background: #047857;
}
.empty-actions {
  display: flex;
  gap: 1.5rem;
  justify-content: center;
  margin-top: 1rem;
}
.big-btn {
  padding: 0.8rem 2rem;
  font-size: 1.1rem;
}

/* AI Box */
.ai-box {
  background: linear-gradient(
    135deg,
    rgba(30, 41, 59, 0.5) 0%,
    rgba(15, 23, 42, 0.5) 100%
  );
  border: 1px solid rgba(139, 92, 246, 0.3);
  padding: 2rem;
  border-radius: 12px;
  margin-bottom: 2rem;
  text-align: center;
  position: relative;
  overflow: hidden;
}
.ai-box::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 2px;
  background: linear-gradient(90deg, #38bdf8, #8b5cf6, #38bdf8);
}
.ai-box h3 {
  color: #f8fafc;
  margin-bottom: 0.5rem;
  justify-content: center;
}
.ai-sparkle {
  color: #8b5cf6;
  margin-right: 8px;
  animation: sparkle 2s infinite;
}
@keyframes sparkle {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.5;
    transform: scale(0.8);
  }
}

.ai-box p {
  color: #94a3b8;
  margin-bottom: 1.5rem;
  font-size: 0.95rem;
}

.ai-upload-btn {
  background: linear-gradient(135deg, #8b5cf6 0%, #38bdf8 100%);
  border: none;
  box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.ai-upload-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(139, 92, 246, 0.5);
}
.ai-upload-btn.is-loading {
  pointer-events: none;
  opacity: 0.9;
}
.ai-upload-btn.is-loading::after {
  content: "";
  position: absolute;
  top: 0;
  left: -100%;
  width: 50%;
  height: 100%;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.2),
    transparent
  );
  animation: loading-sweep 1.5s infinite linear;
}
@keyframes loading-sweep {
  100% {
    left: 100%;
  }
}

.parsing-progress {
  margin-top: 1.5rem;
}
.progress-bar {
  width: 100%;
  max-width: 300px;
  height: 4px;
  background: #334155;
  border-radius: 2px;
  margin: 0 auto 0.5rem auto;
  overflow: hidden;
}
.progress-fill {
  width: 30%;
  height: 100%;
  background: linear-gradient(90deg, #8b5cf6, #38bdf8);
  animation: fill-pulse 2s infinite ease-in-out alternate;
}
@keyframes fill-pulse {
  0% {
    width: 10%;
  }
  100% {
    width: 90%;
  }
}
.parsing-progress small {
  color: #64748b;
}

.empty-resume {
  text-align: center;
  padding: 4rem 1rem;
}
.empty-icon {
  font-size: 3rem;
  margin-bottom: 1rem;
  opacity: 0.8;
}
.empty-resume p {
  font-size: 1.1rem;
  color: #94a3b8;
  margin-bottom: 2rem;
}

/* Info Header */
.info-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 1.5rem;
}
.name {
  margin: 0 0 0.5rem 0;
  color: #f8fafc;
  font-size: 2rem;
  font-weight: 700;
}
.summary {
  color: #94a3b8;
  margin-bottom: 0.5rem;
}
.contact {
  color: #64748b;
  display: flex;
  gap: 1rem;
  font-size: 0.9rem;
}
.avatar-display {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  object-fit: cover;
  border: 3px solid #1e293b;
  box-shadow: 0 0 0 2px #334155;
}
.summary-text {
  background: #1e293b;
  padding: 1rem;
  border-radius: 8px;
  border-left: 4px solid #60a5fa;
}
.summary-text h3 {
  color: #f1f5f9;
  font-size: 1.1rem;
  margin-top: 0;
}
.summary-text p {
  color: #cbd5e1;
  margin: 0;
  line-height: 1.6;
}

/* Date Picker Dark Mode Fix */
input[type="date"]::-webkit-calendar-picker-indicator {
  filter: invert(1);
  opacity: 0.6;
  cursor: pointer;
}
</style>
