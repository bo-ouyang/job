<script setup>
import { onMounted, reactive, ref } from "vue";

import { profileAPI } from "@/api/profile";

const loading = ref(true);
const saving = ref(false);
const message = ref("");
const profile = reactive({
  name: "", phone: "", email: "", city: "", school: "", schoolLevel: "",
  education: "", major: "", graduationYear: "", gpa: "", targetCities: [],
  targetRoles: [], targetIndustries: [], expectedSalary: "", completion: 0,
});
const courses = ref([]);
const skills = ref([]);

const fallback = {
  profile: {
    name: "林晓雨", phone: "", email: "", city: "杭州", school: "浙江理工大学",
    schoolLevel: "普通本科", education: "本科", major: "计算机科学与技术",
    graduationYear: "2027", gpa: "3.6 / 4.0", targetCities: ["杭州", "上海"],
    targetRoles: ["AI 产品经理", "数据产品经理"], targetIndustries: ["互联网 / AI"],
    expectedSalary: "15K–22K", completion: 78,
  },
  courses: [
    { name: "数据结构", category: "专业核心", level: "熟练", core: true, source: "手动添加" },
    { name: "数据库原理", category: "专业核心", level: "掌握", core: true, source: "简历确认" },
    { name: "产品设计基础", category: "跨学科", level: "掌握", core: false, source: "手动添加" },
  ],
  skills: [
    { name: "Python", category: "技术", level: 4, evidence: "课程与项目", source: "简历确认" },
    { name: "SQL", category: "数据", level: 3, evidence: "课程项目", source: "手动添加" },
    { name: "需求分析", category: "产品", level: 3, evidence: "校园项目", source: "简历确认" },
  ],
};

const loadProfile = async () => {
  loading.value = true;
  const [profileResult, courseResult, skillResult] = await Promise.allSettled([
    profileAPI.getProfile(), profileAPI.getCourses(), profileAPI.getSkills(),
  ]);
  Object.assign(profile, profileResult.status === "fulfilled" && profileResult.value?.data
    ? profileResult.value.data : fallback.profile);
  courses.value = courseResult.status === "fulfilled" && Array.isArray(courseResult.value?.data)
    ? courseResult.value.data : fallback.courses;
  skills.value = skillResult.status === "fulfilled" && Array.isArray(skillResult.value?.data)
    ? skillResult.value.data : fallback.skills;
  loading.value = false;
};

const addCourse = () => courses.value.push({ name: "新课程", category: "专业课程", level: "了解", core: false, source: "手动添加" });
const addSkill = () => skills.value.push({ name: "新技能", category: "专业技能", level: 1, evidence: "", source: "手动添加" });
const removeItem = (items, index) => items.splice(index, 1);

const saveProfile = async () => {
  if (saving.value) return;
  saving.value = true;
  message.value = "";
  try {
    await Promise.all([
      profileAPI.updateProfile({ ...profile }),
      profileAPI.saveCourses(courses.value),
      profileAPI.saveSkills(skills.value),
    ]);
    message.value = "个人资料已保存，后续职业分析将使用最新信息。";
  } catch (error) {
    message.value = error?.response?.data?.detail || "保存失败，请稍后重试。";
  } finally {
    saving.value = false;
  }
};

onMounted(loadProfile);
</script>

<template>
  <main class="profile-page">
    <header class="profile-header"><div><p>PERSONAL PROFILE</p><h1>个人资料</h1><span>资料越完整，职业分析越准确。简历解析的信息只有在你确认后才会更新到这里。</span></div><div class="completion-ring"><strong>{{ profile.completion || 0 }}%</strong><span>资料完整度</span></div></header>

    <div class="profile-layout">
      <aside class="profile-nav"><a href="#basic" class="active">基本资料</a><a href="#education">教育与专业</a><a href="#courses">专业课程</a><a href="#skills">专业技能</a><a href="#intentions">求职意向</a><RouterLink to="/my/resume">简历管理</RouterLink><RouterLink to="/my/wallet">余额与账单</RouterLink></aside>

      <div class="profile-content" :aria-busy="loading">
        <section id="basic" class="profile-card" data-section="basic"><header><div><p>BASIC INFORMATION</p><h2>基本信息</h2></div><span>用于账号联系和所在城市分析</span></header><div class="form-grid"><label><span>姓名</span><input v-model="profile.name" /></label><label><span>所在城市</span><input v-model="profile.city" /></label><label><span>手机号</span><input v-model="profile.phone" placeholder="请输入手机号" /></label><label><span>邮箱</span><input v-model="profile.email" placeholder="请输入邮箱" /></label></div></section>

        <section id="education" class="profile-card" data-section="education"><header><div><p>EDUCATION & MAJOR</p><h2>教育与专业</h2></div><span>职业方向与课程分析的核心依据</span></header><div class="form-grid"><label><span>学校</span><input v-model="profile.school" /></label><label><span>学校层次</span><input v-model="profile.schoolLevel" /></label><label><span>学历</span><input v-model="profile.education" /></label><label><span>专业</span><input v-model="profile.major" /></label><label><span>毕业年份</span><input v-model="profile.graduationYear" /></label><label><span>GPA / 成绩排名</span><input v-model="profile.gpa" /></label></div></section>

        <section id="courses" class="profile-card" data-section="courses"><header><div><p>MAJOR COURSES</p><h2>专业课程</h2></div><button @click="addCourse">＋ 添加课程</button></header><div class="item-table course-table"><div class="table-head"><span>课程名称</span><span>分类</span><span>掌握程度</span><span>来源</span><span /></div><div v-for="(item, index) in courses" :key="`${item.name}-${index}`"><input v-model="item.name" /><input v-model="item.category" /><select v-model="item.level"><option>了解</option><option>掌握</option><option>熟练</option><option>精通</option></select><span>{{ item.source || "手动添加" }}</span><button aria-label="删除课程" @click="removeItem(courses, index)">×</button></div></div></section>

        <section id="skills" class="profile-card" data-section="skills"><header><div><p>PROFESSIONAL SKILLS</p><h2>专业技能</h2></div><button @click="addSkill">＋ 添加技能</button></header><div class="skill-items"><article v-for="(item, index) in skills" :key="`${item.name}-${index}`"><div><input v-model="item.name" /><span>{{ item.category }}</span></div><label><span>熟练度</span><input v-model.number="item.level" type="range" min="1" max="5" /><b>{{ item.level }}/5</b></label><p>证据：<input v-model="item.evidence" placeholder="课程、项目或实习" /></p><footer><span>{{ item.source || "手动添加" }}</span><button @click="removeItem(skills, index)">删除</button></footer></article></div></section>

        <section id="intentions" class="profile-card" data-section="intentions"><header><div><p>CAREER INTENTIONS</p><h2>求职意向</h2></div><span>可在职业分析页临时调整筛选</span></header><div class="intention-grid"><div><small>意向城市</small><strong>{{ profile.targetCities?.join('、') || '暂未设置' }}</strong></div><div><small>目标岗位</small><strong>{{ profile.targetRoles?.join('、') || '暂未设置' }}</strong></div><div><small>目标行业</small><strong>{{ profile.targetIndustries?.join('、') || '暂未设置' }}</strong></div><div><small>期望薪资</small><strong>{{ profile.expectedSalary || '暂未设置' }}</strong></div></div></section>

        <footer class="save-bar"><p>{{ message || '保存后，新生成的职业分析会自动使用最新资料。' }}</p><button :disabled="saving" @click="saveProfile">{{ saving ? '保存中…' : '保存全部资料' }}</button></footer>
      </div>
    </div>
  </main>
</template>

<style scoped>
.profile-page { width: min(1240px,calc(100% - 32px)); margin: 0 auto; padding: 42px 0 88px; color: #17253d; }.profile-header { display: flex; align-items: center; justify-content: space-between; gap: 30px; margin-bottom: 28px; }.profile-header p,.profile-card header p { margin: 0 0 7px; color: #55708f; font-size: 12px; font-weight: 800; letter-spacing: .15em; }.profile-header h1 { margin: 0; font-size: 38px; letter-spacing: -.04em; }.profile-header>div>span { display: block; margin-top: 9px; color: #52657d; font-size: 14px; }.completion-ring { display: grid; width: 112px; height: 112px; flex: 0 0 auto; place-items: center; background: radial-gradient(circle,#f4f7fa 56%,transparent 58%),conic-gradient(#176bff 0 78%,#e1e8f0 78%); border-radius: 50%; }.completion-ring strong,.completion-ring span { grid-area: 1/1; }.completion-ring strong { margin-top: -15px; color: #1767dc; font-size: 24px; }.completion-ring span { margin-top: 27px; color: #52657d; font-size: 11px; }.profile-layout { display: grid; grid-template-columns: 205px 1fr; align-items: start; gap: 16px; }.profile-nav { position: sticky; top: 92px; display: grid; padding: 10px; background: #fff; border: 1px solid #e0e7f0; border-radius: 14px; }.profile-nav a { padding: 12px 13px; color: #52657d; border-radius: 8px; font-size: 13px; text-decoration: none; }.profile-nav a:hover,.profile-nav a.active { color: #1767dc; background: #edf4ff; font-weight: 700; }.profile-content { display: grid; gap: 14px; }.profile-card { padding: 22px; background: #fff; border: 1px solid #e0e7f0; border-radius: 14px; box-shadow: 0 8px 25px rgba(42,67,101,.04); scroll-margin-top: 92px; }.profile-card header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }.profile-card h2 { margin: 0; font-size: 20px; }.profile-card header>span { color: #52657d; font-size: 13px; }.profile-card header>button { padding: 8px 11px; color: #1767dc; background: #edf4ff; border: 0; border-radius: 8px; font-size: 12px; font-weight: 700; }.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }.form-grid label { display: grid; gap: 7px; }.form-grid label span { color: #4b6079; font-size: 13px; }.form-grid input,.item-table input,.item-table select,.skill-items input { min-width: 0; padding: 11px 12px; color: #253a54; background: #f8fafc; border: 1px solid #dce4ee; border-radius: 8px; outline: none; font-size: 14px; }.form-grid input:focus,.item-table input:focus,.skill-items input:focus { border-color: #75a6eb; box-shadow: 0 0 0 3px #eaf3ff; }.item-table { display: grid; overflow-x: auto; }.item-table>div { display: grid; min-width: 720px; grid-template-columns: 1.4fr 1fr 1fr 1fr 40px; align-items: center; gap: 10px; min-height: 54px; border-bottom: 1px solid #edf1f5; color: #465a72; font-size: 13px; }.item-table .table-head { min-height: 36px; color: #52657d; background: #f7f9fb; }.item-table>div>* { min-width: 0; }.item-table button { color: #b4545d; background: transparent; border: 0; font-size: 18px; }.skill-items { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }.skill-items article { padding: 15px; background: #f7f9fc; border: 1px solid #e6ebf2; border-radius: 11px; }.skill-items article>div { display: flex; align-items: center; gap: 8px; }.skill-items article>div input { flex: 1; font-weight: 700; }.skill-items article>div span,.skill-items footer span { color: #52657d; font-size: 12px; }.skill-items label { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 8px; margin: 13px 0; color: #52657d; font-size: 12px; }.skill-items label input { padding: 0; }.skill-items p { display: flex; align-items: center; gap: 7px; color: #52657d; font-size: 12px; }.skill-items p input { flex: 1; }.skill-items footer { display: flex; justify-content: space-between; align-items: center; }.skill-items footer button { color: #b4545d; background: transparent; border: 0; font-size: 12px; }.intention-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 10px; }.intention-grid>div { min-height: 82px; padding: 14px; background: #f5f8fb; border-radius: 9px; }.intention-grid small,.intention-grid strong { display: block; }.intention-grid small { color: #52657d; font-size: 12px; }.intention-grid strong { margin-top: 8px; color: #263b54; font-size: 14px; line-height: 1.5; }.save-bar { position: sticky; bottom: 14px; z-index: 3; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 15px 18px; background: rgba(255,255,255,.96); border: 1px solid #dce5ef; border-radius: 13px; box-shadow: 0 15px 40px rgba(24,51,88,.14); }.save-bar p { margin: 0; color: #52657d; font-size: 13px; }.save-bar button { padding: 11px 17px; color: #fff; background: #1767dc; border: 0; border-radius: 9px; font-size: 13px; font-weight: 700; }.save-bar button:disabled { opacity: .6; }
@media(max-width:900px){.profile-layout{grid-template-columns:1fr}.profile-nav{position:static;display:flex;overflow-x:auto}.profile-nav a{flex:0 0 auto}.intention-grid{grid-template-columns:1fr 1fr}}
@media(max-width:620px){.profile-page{width:calc(100% - 24px);padding:28px 0 85px}.profile-header{align-items:flex-start}.completion-ring{display:none}.profile-header h1{font-size:32px}.form-grid,.skill-items,.intention-grid{grid-template-columns:1fr}.profile-card{padding:17px}.profile-card header{align-items:flex-start;flex-direction:column}.save-bar{align-items:stretch;flex-direction:column}.save-bar button{width:100%}}
</style>
