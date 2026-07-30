<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { useResumeStore } from "../stores/resume";
import { useAiTaskStore } from "@/stores/aiTask";
import { aiAPI } from "@/api/ai";
import { profileAPI } from "@/api/profile";
import { storeToRefs } from "pinia";

const store = useResumeStore();
const aiTaskStore = useAiTaskStore();
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

// --- AI resume parsing and candidate confirmation ---
const parsingStatus = ref("");
const parseError = ref("");
const parseCandidates = ref([]);
const applyingCandidates = ref(false);
const activeParseTaskId = ref("");
const isParseBusy = computed(() =>
  ["uploading", "parsing", "saving"].includes(parsingStatus.value),
);

const BASIC_FIELDS = [
  ["name", "姓名"],
  ["phone", "手机号码"],
  ["email", "邮箱"],
  ["gender", "性别"],
  ["age", "年龄"],
  ["desired_position", "期望职位"],
  ["summary", "个人优势"],
];

const displayValue = (value) => {
  if (Array.isArray(value)) return value.filter(Boolean).join("、");
  if (value && typeof value === "object") {
    return value.school || value.company || value.name || JSON.stringify(value);
  }
  return String(value ?? "");
};

const normalizeTaskPayload = (result) => {
  let payload = result?.result_payload || result?.resultPayload || result || {};
  if (typeof payload?.result_data === "string") {
    try {
      payload = { ...payload, ...JSON.parse(payload.result_data) };
    } catch (_) {
      // The backend validation prevents malformed successful resume results.
    }
  }
  return payload && typeof payload === "object" ? payload : {};
};

const buildParseCandidates = (payload) => {
  const candidates = [];
  for (const [field, label] of BASIC_FIELDS) {
    if (payload[field] !== undefined && payload[field] !== null && payload[field] !== "") {
      candidates.push({
        id: `basic:${field}`,
        kind: "basic",
        field,
        label,
        value: payload[field],
        currentValue: resume.value?.[field] || "",
        selected: true,
      });
    }
  }

  (payload.educations || []).forEach((item, index) => {
    if (!item?.school) return;
    candidates.push({
      id: `education:${index}`,
      kind: "education",
      label: "教育经历",
      value: item,
      currentValue: "",
      selected: true,
    });
  });
  (payload.work_experiences || []).forEach((item, index) => {
    if (!item?.company || !item?.position) return;
    candidates.push({
      id: `work:${index}`,
      kind: "work",
      label: "工作经历",
      value: item,
      currentValue: "",
      selected: true,
    });
  });
  (payload.skills || []).forEach((item, index) => {
    const name = typeof item === "string" ? item : item?.name;
    if (!name) return;
    candidates.push({
      id: `skill:${index}`,
      kind: "skill",
      label: "专业技能",
      value: { ...(typeof item === "object" ? item : {}), name },
      currentValue: "",
      selected: true,
    });
  });
  (payload.courses || []).forEach((item, index) => {
    const name = typeof item === "string" ? item : item?.name;
    if (!name) return;
    candidates.push({
      id: `course:${index}`,
      kind: "course",
      label: "专业课程",
      value: { ...(typeof item === "object" ? item : {}), name },
      currentValue: "",
      selected: true,
    });
  });
  return candidates;
};

const errorMessage = (error) => {
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => `${item.loc?.slice(-1)?.[0] || "字段"}：${item.msg || "格式不正确"}`)
      .join("；");
  }
  return String(
    detail ||
      error?.response?.data?.message ||
      error?.message ||
      error ||
      "简历解析失败，请稍后重试",
  );
};

const handleSmartParse = async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;

  parseError.value = "";
  parseCandidates.value = [];
  parsingStatus.value = "uploading";
  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await aiAPI.parseResume(formData);
    const taskId = response.data?.task_id;
    if (!taskId) throw new Error("解析任务创建失败：后端未返回任务编号");

    aiTaskStore.addTask(taskId, "resume_parse", { filename: file.name });
    activeParseTaskId.value = taskId;
    parsingStatus.value = "parsing";
    const result = await aiTaskStore.pollAndUpdate(taskId, { timeout: 120000 });
    const candidates = buildParseCandidates(normalizeTaskPayload(result));
    if (!candidates.length) throw new Error("未从简历中识别出可更新的资料");

    parseCandidates.value = candidates;
    parsingStatus.value = "review";
  } catch (error) {
    parsingStatus.value = "error";
    parseError.value = errorMessage(error);
  } finally {
    event.target.value = "";
  }
};

const normalizedDate = (value) => (
  /^\d{4}-\d{2}-\d{2}$/.test(String(value || "")) ? value : undefined
);

const cleanEducation = (item) => ({
  school: String(item.school || "").trim(),
  major: item.major || undefined,
  degree: item.degree || undefined,
  start_date: normalizedDate(item.start_date),
  end_date: normalizedDate(item.end_date),
  description: item.description || undefined,
});

const cleanWork = (item) => ({
  company: String(item.company || "").trim(),
  position: String(item.position || "").trim(),
  department: item.department || undefined,
  start_date: normalizedDate(item.start_date),
  end_date: normalizedDate(item.end_date),
  content: item.content || undefined,
  achievement: item.achievement || undefined,
});

const confirmParsedCandidates = async () => {
  const selected = parseCandidates.value.filter((item) => item.selected);
  if (!selected.length) {
    parseError.value = "请至少选择一项需要保存的资料";
    return;
  }

  applyingCandidates.value = true;
  parsingStatus.value = "saving";
  parseError.value = "";
  try {
    const basicPayload = Object.fromEntries(
      selected
        .filter((item) => item.kind === "basic")
        .map((item) => [item.field, item.value]),
    );
    if (basicPayload.phone && !/^1[3-9]\d{9}$/.test(String(basicPayload.phone))) {
      throw new Error("解析出的手机号码格式不正确，请取消该项或重新上传简历");
    }
    if (basicPayload.gender && !["男", "女"].includes(basicPayload.gender)) {
      throw new Error("解析出的性别格式不正确，请取消该项或重新上传简历");
    }
    if (basicPayload.age && (Number(basicPayload.age) < 16 || Number(basicPayload.age) > 100)) {
      throw new Error("解析出的年龄不在 16 至 100 岁范围内，请取消该项或重新上传简历");
    }

    const educations = selected
      .filter((item) => item.kind === "education")
      .map((item) => cleanEducation(item.value));
    const works = selected
      .filter((item) => item.kind === "work")
      .map((item) => cleanWork(item.value));

    await profileAPI.applyResumeCandidates({
      basic: basicPayload,
      educations,
      workExperiences: works,
      skills: selected
        .filter((item) => item.kind === "skill")
        .map((item) => ({
          name: item.value.name,
          category: item.value.category || null,
          proficiencyLevel: item.value.proficiencyLevel ?? item.value.proficiency_level ?? 3,
          yearsExperience: item.value.yearsExperience ?? item.value.years_experience ?? null,
          source: "resume",
          confirmationStatus: "confirmed",
          evidence: item.value.evidence ?? null,
        })),
      courses: selected
        .filter((item) => item.kind === "course")
        .map((item) => ({
          name: item.value.name,
          category: item.value.category || null,
          level: item.value.level || null,
          isCore: item.value.isCore ?? item.value.is_core ?? false,
          source: "resume",
          confirmationStatus: "confirmed",
          evidence: item.value.evidence ?? null,
        })),
    });

    await store.fetchMyResume();
    parseCandidates.value = [];
    parsingStatus.value = "success";
    activeParseTaskId.value = "";
    isEditingBasic.value = false;
  } catch (error) {
    parsingStatus.value = "review";
    parseError.value = errorMessage(error);
  } finally {
    applyingCandidates.value = false;
  }
};

const onWsMessage = (event) => {
  const message = event.detail;
  if (message?.type === "resume_parse_error") {
    if (!message.data?.task_id || message.data.task_id !== activeParseTaskId.value) return;
    parsingStatus.value = "error";
    parseError.value = message.data?.message || "简历解析失败，请稍后重试";
  }
};

onMounted(() => window.addEventListener("ws-message", onWsMessage));
onUnmounted(() => window.removeEventListener("ws-message", onWsMessage));

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
              :class="{ 'is-loading': isParseBusy }"
            >
              <span v-if="!parsingStatus || parsingStatus === 'error' || parsingStatus === 'success'">✨ 上传 PDF 智能生成</span>
              <span v-else-if="parsingStatus === 'uploading'"
                >🚀 正在上传...</span
              >
              <span v-else-if="parsingStatus === 'parsing'"
                >🧠 AI 深度解析中...</span
              >
              <span v-else-if="parsingStatus === 'review'">📋 请确认解析结果</span>
              <span v-else-if="parsingStatus === 'saving'">正在保存资料...</span>
              <input
                type="file"
                @change="handleSmartParse"
                accept=".pdf"
                hidden
                :disabled="isParseBusy"
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
                :class="{ 'is-loading': isParseBusy }"
              >
                <span v-if="!parsingStatus || parsingStatus === 'error' || parsingStatus === 'success'">上传并解析 PDF</span>
                <span v-else-if="parsingStatus === 'uploading'"
                  >🚀 正在上传...</span
                >
                <span v-else-if="parsingStatus === 'parsing'"
                  >🧠 AI 深度解析中...</span
                >
                <span v-else-if="parsingStatus === 'review'">📋 请确认下方解析结果</span>
                <span v-else-if="parsingStatus === 'saving'">正在保存资料...</span>
                <input
                  type="file"
                  @change="handleSmartParse"
                  accept=".pdf"
                  hidden
                  :disabled="isParseBusy"
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

      <section v-if="parseError" class="parse-error" role="alert">
        <strong>简历处理未完成</strong>
        <span>{{ parseError }}</span>
      </section>

      <section
        v-if="parseCandidates.length"
        class="section parse-preview"
        data-testid="resume-parse-preview"
      >
        <div class="section-header parse-preview-header">
          <div>
            <small>PARSE PREVIEW</small>
            <h3>待确认的资料更新</h3>
            <p>解析结果不会自动覆盖资料，请勾选确认后再保存。</p>
          </div>
          <span>{{ parseCandidates.filter((item) => item.selected).length }} 项已选择</span>
        </div>
        <div class="candidate-list">
          <label v-for="candidate in parseCandidates" :key="candidate.id" class="candidate-row">
            <input v-model="candidate.selected" type="checkbox" />
            <span class="candidate-copy">
              <small>{{ candidate.label }}</small>
              <span v-if="candidate.currentValue" class="candidate-current">
                {{ displayValue(candidate.currentValue) }} →
              </span>
              <strong>{{ displayValue(candidate.value) }}</strong>
            </span>
            <em>{{ candidate.currentValue ? "修改" : "新增" }}</em>
          </label>
        </div>
        <footer class="parse-preview-footer">
          <p>保存后会同步更新结构化简历和职业分析使用的个人资料。</p>
          <button
            class="btn-primary"
            data-testid="confirm-resume-candidates"
            :disabled="applyingCandidates"
            @click="confirmParsedCandidates"
          >
            {{ applyingCandidates ? "保存中..." : "保存选中项" }}
          </button>
        </footer>
      </section>

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

.parse-error {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  padding: 1rem 1.25rem;
  color: #fecaca;
  background: #451a1a;
  border: 1px solid #7f1d1d;
  border-radius: 10px;
}
.parse-error span {
  color: #fca5a5;
}
.parse-preview-header small {
  color: #60a5fa;
  font-weight: 700;
  letter-spacing: 0.12em;
}
.parse-preview-header h3 {
  margin: 0.35rem 0;
}
.parse-preview-header p,
.parse-preview-footer p {
  margin: 0;
  color: #94a3b8;
}
.parse-preview-header > span {
  color: #fbbf24;
  font-weight: 700;
}
.candidate-list {
  display: grid;
  gap: 0.75rem;
}
.candidate-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.9rem;
  align-items: center;
  padding: 1rem;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 9px;
  cursor: pointer;
}
.candidate-row input {
  width: 18px;
  height: 18px;
}
.candidate-copy {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  align-items: baseline;
  min-width: 0;
}
.candidate-copy small {
  width: 100%;
  color: #94a3b8;
}
.candidate-copy strong {
  color: #f8fafc;
  overflow-wrap: anywhere;
}
.candidate-current {
  color: #64748b;
  text-decoration: line-through;
}
.candidate-row em {
  color: #86efac;
  font-size: 0.8rem;
  font-style: normal;
}
.parse-preview-footer {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: center;
  margin-top: 1rem;
}

@media (max-width: 640px) {
  .parse-error,
  .parse-preview-footer {
    align-items: stretch;
    flex-direction: column;
  }
  .candidate-row {
    grid-template-columns: auto 1fr;
  }
  .candidate-row em {
    grid-column: 2;
  }
}
</style>
