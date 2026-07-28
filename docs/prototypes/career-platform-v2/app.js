const pages = [...document.querySelectorAll("[data-page-panel]")];
const navItems = [...document.querySelectorAll(".nav-item")];
const chargeModal = document.querySelector("#chargeModal");
const chargeTitle = document.querySelector("#chargeTitle");
const chargeCost = document.querySelector("#chargeCost");
const toast = document.querySelector("#toast");
const homeAiDialog = document.querySelector("#homeAiDialog");
const homeAiLauncher = document.querySelector(".home-ai-launcher");

function showToast(message) {
  toast.querySelector("p").textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2200);
}

function openPage(name) {
  pages.forEach((page) => page.classList.toggle("active", page.dataset.pagePanel === name));
  navItems.forEach((item) => item.classList.toggle("active", item.dataset.page === name));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.querySelectorAll(".nav-trigger, .nav-item").forEach((button) => {
  button.addEventListener("click", () => openPage(button.dataset.page));
});

document.querySelectorAll(".filter-button").forEach((button) => {
  button.addEventListener("click", () => showToast("筛选条件已更新"));
});

document.querySelector(".home-ai-close").addEventListener("click", () => {
  homeAiDialog.classList.remove("open");
  homeAiDialog.setAttribute("aria-hidden", "true");
  homeAiLauncher.classList.add("visible");
  homeAiLauncher.setAttribute("aria-expanded", "false");
  homeAiLauncher.setAttribute("aria-hidden", "false");
});

homeAiLauncher.addEventListener("click", () => {
  homeAiDialog.classList.add("open");
  homeAiDialog.setAttribute("aria-hidden", "false");
  homeAiLauncher.classList.remove("visible");
  homeAiLauncher.setAttribute("aria-expanded", "true");
  homeAiLauncher.setAttribute("aria-hidden", "true");
});

document.querySelectorAll(".charge-trigger").forEach((button) => {
  button.addEventListener("click", () => {
    chargeTitle.textContent = button.dataset.action || "确认使用 AI 服务";
    chargeCost.textContent = button.dataset.cost || "0.20";
    chargeModal.classList.add("open");
    chargeModal.setAttribute("aria-hidden", "false");
  });
});

function closeModal() {
  chargeModal.classList.remove("open");
  chargeModal.setAttribute("aria-hidden", "true");
}

document.querySelector(".modal-close").addEventListener("click", closeModal);
chargeModal.addEventListener("click", (event) => {
  if (event.target === chargeModal) closeModal();
});
document.querySelector("#confirmCharge").addEventListener("click", () => {
  closeModal();
  showToast("AI 任务已创建，费用已冻结");
});

const fileInput = document.querySelector("#fileInput");
document.querySelector("#uploadButton").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  if (fileInput.files?.length) showToast(`${fileInput.files[0].name} 已进入解析队列`);
});

document.querySelector("#acceptAll").addEventListener("click", () => {
  document.querySelectorAll(".diff-list input").forEach((input) => { input.checked = true; });
  showToast("已选择全部资料变更");
});
document.querySelector("#saveResumeChanges").addEventListener("click", () => showToast("资料更新已保存"));
document.querySelector("#rechargeButton").addEventListener("click", () => showToast("正在打开支付页面"));

document.querySelectorAll(".amount-grid button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".amount-grid button").forEach((item) => item.classList.remove("selected"));
    button.classList.add("selected");
    const amount = button.textContent.match(/¥\d+/)?.[0] || "所选金额";
    document.querySelector("#rechargeButton").textContent = `立即充值 ${amount}`;
  });
});
