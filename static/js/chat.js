const DEFAULT_WORD_COUNT_WAN = 2;
const DEFAULT_EPISODE_COUNT = 10;
const DEFAULT_CURRENT_EPISODE = 1;
const POLL_INTERVAL = 2000;
const SLOW_HINT_AFTER_MS = 18000;
const VERY_SLOW_HINT_AFTER_MS = 32000;

let currentTaskId = null;
let currentProjectId = null;
let pollingTimer = null;
let lastTraceCount = 0;
let lastTraceUpdateMs = 0;
let taskStartedMs = 0;

const STAGE_ORDER_MAP = {
  outline: [
    { stage: "queued", label: "已创建任务" },
    { stage: "character_bible", label: "人物设定" },
    { stage: "plot_outline", label: "剧情大纲" },
    { stage: "review_report", label: "审核意见" },
    { stage: "final_script", label: "最终总纲" }
  ],
  episode_plan: [
    { stage: "queued", label: "已创建任务" },
    { stage: "character_bible", label: "人物设定" },
    { stage: "plot_outline", label: "分集计划" },
    { stage: "review_report", label: "审核意见" },
    { stage: "final_script", label: "最终分集稿" }
  ],
  single_episode_script: [
    { stage: "queued", label: "已创建任务" },
    { stage: "character_bible", label: "角色基础" },
    { stage: "plot_outline", label: "本集计划" },
    { stage: "final_script", label: "单集剧本" }
  ],
  scene_asset_extract: [
    { stage: "queued", label: "已创建任务" },
    { stage: "plot_outline", label: "场景识别" },
    { stage: "final_script", label: "场景资产" }
  ],
  multi_episode_script: [
    { stage: "queued", label: "已创建任务" },
    { stage: "character_bible", label: "角色基础" },
    { stage: "plot_outline", label: "分集计划" },
    { stage: "final_script", label: "多集剧本" }
  ]
};

const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");
const messageInput = document.getElementById("messageInput");
const wordCountInput = document.getElementById("wordCountInput");
const episodeCountInput = document.getElementById("episodeCountInput");
const projectIdText = document.getElementById("projectIdText");
const taskIdText = document.getElementById("taskIdText");
const taskStatusText = document.getElementById("taskStatusText");
const currentModelText = document.getElementById("currentModelText");

const finalScriptBox = document.getElementById("finalScriptBox");
const characterBox = document.getElementById("characterBox");
const outlineBox = document.getElementById("outlineBox");
const reviewBox = document.getElementById("reviewBox");
const traceBox = document.getElementById("traceBox");

const messageList = document.getElementById("messageList");
const storyExportBtn = document.getElementById("storyExportBtn");
const scriptExportBtn = document.getElementById("scriptExportBtn");
const editScriptBtn = document.getElementById("editScriptBtn");
const characterDetailBtn = document.getElementById("characterDetailBtn");
const chapterDetailBtn = document.getElementById("chapterDetailBtn");
const modelSelect = document.getElementById("modelSelect");

const stagePillText = document.getElementById("stagePillText");
const stageTitleText = document.getElementById("stageTitleText");
const stageHintText = document.getElementById("stageHintText");
const progressBarFill = document.getElementById("progressBarFill");
const progressPercentText = document.getElementById("progressPercentText");
const progressStepList = document.getElementById("progressStepList");
const timelineList = document.getElementById("timelineList");
const timelineCountText = document.getElementById("timelineCountText");
const slowTipText = document.getElementById("slowTipText");

const genreInput = document.getElementById("genreInput");
const styleInput = document.getElementById("styleInput");
const granularitySelect = document.getElementById("granularitySelect");
const modeSelect = document.getElementById("modeSelect");
const referenceInput = document.getElementById("referenceInput");
const frameworkInput = document.getElementById("frameworkInput");
const bannedInput = document.getElementById("bannedInput");
const currentEpisodeInput = document.getElementById("currentEpisodeInput");
const episodeCounterText = document.getElementById("episodeCounterText");


function getCurrentGranularity() {
  return granularitySelect ? granularitySelect.value : "outline";
}

function getStageOrder() {
  const value = getCurrentGranularity();
  return STAGE_ORDER_MAP[value] || STAGE_ORDER_MAP.outline;
}

function getFinalTabLabel(granularity) {
  switch (granularity) {
    case "outline":
    case "episode_plan":
      return "总编剧定稿";
    case "multi_episode_script":
      return "多集剧本";
    case "scene_asset_extract":
      return "场景资产";
    case "single_episode_script":
      return "单集剧本";
    default:
      return "最终稿";
  }
}

function getFinalPlaceholder(granularity) {
  switch (granularity) {
    case "outline":
      return "暂无最终总纲";
    case "episode_plan":
      return "暂无最终分集稿";
    case "single_episode_script":
      return "暂无单集剧本";
    case "scene_asset_extract":
      return "暂无场景资产";
    case "multi_episode_script":
      return "暂无多集剧本";
    default:
      return "暂无最终稿";
  }
}

function updateFinalTabLabel() {
  const finalTabBtn = document.querySelector('.tab-btn[data-tab="final"]');
  if (finalTabBtn) {
    finalTabBtn.textContent = getFinalTabLabel(getCurrentGranularity());
  }
}

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDisplayTime(isoText) {
  if (!isoText) return "";
  const date = new Date(isoText);
  if (Number.isNaN(date.getTime())) return isoText;
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function formatStatusLabel(status) {
  if (status === "pending") return "已创建";
  if (status === "running") return "进行中";
  if (status === "done") return "已完成";
  if (status === "failed") return "失败";
  return "空闲";
}

function switchTab(tabName) {
  const btn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
  if (btn) btn.click();
}

function addMessage(role, text) {
  if (!messageList) return;
  const wrap = document.createElement("div");
  wrap.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  wrap.appendChild(bubble);
  messageList.appendChild(wrap);
  messageList.scrollTop = messageList.scrollHeight;
}

function disableLegacyLinks() {
  [storyExportBtn, scriptExportBtn, editScriptBtn, characterDetailBtn, chapterDetailBtn].forEach((a) => {
    if (!a) return;
    a.classList.add("disabled");
    a.href = "#";
  });
}

function enableLegacyLinks(projectId) {
  if (storyExportBtn) storyExportBtn.href = `/dashboard/script/${projectId}/export_story_txt`;
  if (scriptExportBtn) scriptExportBtn.href = `/dashboard/script/${projectId}/export_script_txt`;
  if (editScriptBtn) editScriptBtn.href = `/dashboard/script/${projectId}/edit?tab=basic`;
  if (characterDetailBtn) characterDetailBtn.href = `/dashboard/script/${projectId}/edit?tab=characters`;
  if (chapterDetailBtn) chapterDetailBtn.href = `/chapters/script/${projectId}/chapters`;

  [storyExportBtn, scriptExportBtn, editScriptBtn, characterDetailBtn, chapterDetailBtn].forEach((a) => {
    if (!a) return;
    a.classList.remove("disabled");
  });
}

function setIdleProgressCard() {
  if (stagePillText) stagePillText.textContent = "空闲";
  if (stageTitleText) stageTitleText.textContent = "等待开始";

  const granularity = getCurrentGranularity();
  const finalLabel = getFinalTabLabel(granularity);

  if (stageHintText) {
    stageHintText.textContent = `输入需求后，系统会先搭建人物，再整理剧情，最后输出${finalLabel}。`;
  }

  if (progressPercentText) progressPercentText.textContent = "0%";
  if (progressBarFill) progressBarFill.style.width = "0%";
  if (slowTipText) slowTipText.textContent = "";
  if (episodeCounterText) episodeCounterText.textContent = "";
  renderProgressSteps("", "idle");
}

function renderProgressSteps(currentStage, status) {
  if (!progressStepList) return;

  const stageOrder = getStageOrder();
  const currentIndex = stageOrder.findIndex((item) => item.stage === currentStage);
  const allDone = status === "done";

  progressStepList.innerHTML = stageOrder.map((item, idx) => {
    let stateClass = "pending";
    let marker = "○";

    if (allDone || (currentIndex !== -1 && idx < currentIndex)) {
      stateClass = "done";
      marker = "✓";
    } else if (!allDone && currentIndex !== -1 && idx === currentIndex) {
      stateClass = status === "failed" ? "failed" : "active";
      marker = status === "failed" ? "!" : "•";
    }

    return `
      <li class="${stateClass}">
        <span class="step-marker">${marker}</span>
        <span class="step-label">${escapeHtml(item.label)}</span>
      </li>
    `;
  }).join("");
}

function updateProgressCardFromTask(task) {
  const progress = Math.max(0, Math.min(100, Number(task.progress || 0)));
  if (stagePillText) stagePillText.textContent = formatStatusLabel(task.status);
  if (stageTitleText) stageTitleText.textContent = task.current_title || "处理中";
  if (stageHintText) stageHintText.textContent = task.current_message || "";
  if (progressPercentText) progressPercentText.textContent = `${Math.round(progress)}%`;
  if (progressBarFill) progressBarFill.style.width = `${progress}%`;
  renderProgressSteps(task.current_stage, task.status);
  updateEpisodeCounter(task);
}

function updateSlowTip(task) {
  if (!slowTipText) return;

  if (!task || task.status !== "running") {
    slowTipText.textContent = "";
    return;
  }

  const anchor = lastTraceUpdateMs || taskStartedMs || Date.now();
  const diff = Date.now() - anchor;

  if (diff >= VERY_SLOW_HINT_AFTER_MS) {
    slowTipText.textContent = "当前内容较长，正在继续生成，请稍等。";
  } else if (diff >= SLOW_HINT_AFTER_MS) {
    slowTipText.textContent = "这一阶段会稍慢一些，我还在继续整理。";
  } else {
    slowTipText.textContent = "";
  }
}

function renderTimeline(trace) {
  if (!timelineList) return;

  if (!trace || trace.length === 0) {
    timelineList.innerHTML = `<div class="timeline-empty">任务开始后，这里会显示系统的创作过程。</div>`;
    if (timelineCountText) timelineCountText.textContent = "0 条更新";
    return;
  }

  timelineList.innerHTML = trace.map((item) => {
    return `
      <div class="timeline-item ${escapeHtml(item.status || "running")}">
        <div class="timeline-dot"></div>
        <div class="timeline-body">
          <div class="timeline-top">
            <strong>${escapeHtml(item.title || item.stage || "阶段更新")}</strong>
            <span>${escapeHtml(formatDisplayTime(item.time))}</span>
          </div>
          <div class="timeline-message">${escapeHtml(item.message || "").replaceAll("\n", "<br>")}</div>
          ${item.preview ? `<div class="timeline-preview">${escapeHtml(item.preview)}</div>` : ""}
        </div>
      </div>
    `;
  }).join("");

  if (timelineCountText) timelineCountText.textContent = `${trace.length} 条更新`;
}

function renderTraceTab(trace) {
  if (!traceBox) return;

  if (!trace || trace.length === 0) {
    traceBox.innerHTML = `<div class="trace-empty">暂无生成过程</div>`;
    return;
  }

  traceBox.innerHTML = trace.map((item, idx) => {
    return `
      <div class="trace-entry">
        <div class="trace-entry-head">
          <strong>#${idx + 1} ${escapeHtml(item.title || item.stage || "阶段更新")}</strong>
          <span>${escapeHtml(formatDisplayTime(item.time))}</span>
        </div>
        <div class="trace-entry-meta">阶段：${escapeHtml(item.step || item.stage || "")} ｜ 状态：${escapeHtml(formatStatusLabel(item.status || ""))}</div>
        <div class="trace-entry-message">${escapeHtml(item.message || "").replaceAll("\n", "<br>")}</div>
        ${item.preview ? `<div class="trace-entry-preview">${escapeHtml(item.preview)}</div>` : ""}
      </div>
    `;
  }).join("");
}

function syncNewTraceMessages(trace) {
  if (!trace || trace.length <= lastTraceCount) return;

  const newItems = trace.slice(lastTraceCount);
  newItems.forEach((item) => {
    const lines = [];
    if (item.title) lines.push(item.title);
    if (item.message) lines.push(item.message);
    if (item.preview && item.status === "done") lines.push(`阶段摘要：${item.preview}`);
    addMessage("system", lines.join("\n"));
  });

  lastTraceCount = trace.length;
  lastTraceUpdateMs = Date.now();
}

function renderArtifacts(data) {
  const granularity = getCurrentGranularity();

  let finalText = "";

  if (granularity === "multi_episode_script" || granularity === "single_episode_script") {
    finalText = data.script_text || data.final_script || "";
  } else if (granularity === "outline" || granularity === "episode_plan") {
    finalText = data.final_review || "";
  } else if (granularity === "scene_asset_extract") {
    finalText = data.final_script || "";
  }

  const characterText = data.character_bible || data.character_profile || "";
  const outlineText = data.plot_outline || data.episode_plan || data.outline || "";
  const reviewText = data.review_report || data.review || "";

  if (finalScriptBox) finalScriptBox.textContent = finalText || getFinalPlaceholder(granularity);
  if (characterBox) characterBox.textContent = characterText || "暂无人物设定";
  if (outlineBox) outlineBox.textContent = outlineText || "暂无剧情大纲";
  if (reviewBox) reviewBox.textContent = reviewText || "暂无审核意见";
}

async function safeReadJson(resp) {
  const text = await resp.text();
  const contentType = resp.headers.get("content-type") || "";

  if (!contentType.includes("application/json")) {
    throw new Error(`接口没有返回 JSON。HTTP ${resp.status}，前 200 字符：${text.slice(0, 200)}`);
  }

  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error(`JSON 解析失败：${e.message}`);
  }
}

async function loadArtifacts(projectId) {
  const resp = await fetch(`${window.chatConfig.projectBaseUrl}${projectId}/artifacts`);
  const data = await safeReadJson(resp);
  if (!resp.ok || !data.success) {
    throw new Error(data.message || "加载结果失败");
  }
  renderArtifacts(data);
  return data;
}

async function loadTrace(projectId) {
  const resp = await fetch(`${window.chatConfig.projectBaseUrl}${projectId}/trace`);
  const data = await safeReadJson(resp);
  if (!resp.ok || !data.success) {
    throw new Error(data.message || "加载过程失败");
  }
  renderTimeline(data.trace || []);
  renderTraceTab(data.trace || []);
  syncNewTraceMessages(data.trace || []);
  return data.trace || [];
}

async function refreshProjectPanels(projectId) {
  const [trace, artifacts] = await Promise.all([
    loadTrace(projectId),
    loadArtifacts(projectId)
  ]);
  return { trace, artifacts };
}

function resetChatState() {
  currentTaskId = null;
  currentProjectId = null;
  lastTraceCount = 0;
  lastTraceUpdateMs = 0;
  taskStartedMs = 0;

  if (projectIdText) projectIdText.textContent = "未创建";
  if (taskIdText) taskIdText.textContent = "未开始";
  if (taskStatusText) taskStatusText.textContent = "空闲";

  if (finalScriptBox) finalScriptBox.textContent = "暂无内容";
  if (characterBox) characterBox.textContent = "暂无内容";
  if (outlineBox) outlineBox.textContent = "暂无内容";
  if (reviewBox) reviewBox.textContent = "暂无内容";
  if (traceBox) traceBox.innerHTML = `<div class="trace-empty">暂无生成过程</div>`;
  if (timelineList) timelineList.innerHTML = `<div class="timeline-empty">任务开始后，这里会显示系统的创作过程。</div>`;
  if (timelineCountText) timelineCountText.textContent = "0 条更新";

  disableLegacyLinks();
  updateFinalTabLabel();
  setIdleProgressCard();

  if (pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
}

function normalizePositiveFloat(inputEl, fallbackValue) {
  let value = inputEl ? parseFloat(inputEl.value) : fallbackValue;
  if (Number.isNaN(value) || value <= 0) {
    value = fallbackValue;
    if (inputEl) inputEl.value = fallbackValue;
  }
  return value;
}

function normalizePositiveInt(inputEl, fallbackValue) {
  let value = inputEl ? parseInt(inputEl.value, 10) : fallbackValue;
  if (Number.isNaN(value) || value <= 0) {
    value = fallbackValue;
    if (inputEl) inputEl.value = fallbackValue;
  }
  return value;
}

async function handleSend() {
  const message = messageInput ? messageInput.value.trim() : "";
  if (!message) {
    alert("请填写“用户输入”");
    return;
  }

  if (sendBtn) sendBtn.disabled = true;

  lastTraceCount = 0;
  lastTraceUpdateMs = 0;
  taskStartedMs = Date.now();

  if (finalScriptBox) finalScriptBox.textContent = "暂无内容";
  if (characterBox) characterBox.textContent = "暂无内容";
  if (outlineBox) outlineBox.textContent = "暂无内容";
  if (reviewBox) reviewBox.textContent = "暂无内容";
  if (traceBox) traceBox.innerHTML = `<div class="trace-empty">正在等待生成过程...</div>`;
  if (timelineList) timelineList.innerHTML = `<div class="timeline-empty">正在创建任务...</div>`;
  if (timelineCountText) timelineCountText.textContent = "0 条更新";

  try {
    const wordCountWan = normalizePositiveFloat(wordCountInput, DEFAULT_WORD_COUNT_WAN);
    const episodeCount = normalizePositiveInt(episodeCountInput, DEFAULT_EPISODE_COUNT);
    const currentEpisodeNo = normalizePositiveInt(currentEpisodeInput, DEFAULT_CURRENT_EPISODE);

    const genre = genreInput ? genreInput.value.trim() : "";
    const style = styleInput ? styleInput.value.trim() : "";
    const outputGranularity = getCurrentGranularity();
    const mode = modeSelect ? modeSelect.value : "";
    const referenceText = referenceInput ? referenceInput.value.trim() : "";
    const frameworkText = frameworkInput ? frameworkInput.value.trim() : "";
    const banned = bannedInput ? bannedInput.value.trim() : "";

    updateFinalTabLabel();
    setIdleProgressCard();

    const summaryLines = [`〖字数〗${wordCountWan}万字`];
    if (episodeCount) summaryLines.push(`〖集数〗${episodeCount}`);
    if (outputGranularity === "single_episode_script") {
      summaryLines.push(`〖当前集〗第${currentEpisodeNo}集`);
    }
    if (genre) summaryLines.push(`〖题材〗${genre}`);
    if (style) summaryLines.push(`〖风格〗${style}`);
    if (outputGranularity) summaryLines.push(`〖输出粒度〗${outputGranularity}`);
    if (mode) summaryLines.push(`〖模式〗${mode}`);
    if (frameworkText) summaryLines.push(`〖框架〗${frameworkText}`);
    if (referenceText) summaryLines.push(`〖参考〗${referenceText}`);
    if (banned) summaryLines.push(`〖禁止项〗${banned}`);
    summaryLines.push(`〖需求〗${message}`);

    addMessage("user", summaryLines.join("\n"));
    addMessage("system", "已收到你的需求，我会先搭人物，再搭剧情，再做审核和整合。");

    const payload = {
      project_id: currentProjectId,
      message: message,
      meta: {
        word_count_wan: wordCountWan,
        episode_count: episodeCount,
        genre: genre,
        style: style,
        output_granularity: outputGranularity,
        mode: mode,
        reference_text: referenceText,
        framework_text: frameworkText,
        banned: banned,
        banned_items: banned,
        current_episode: currentEpisodeNo
      }
    };

    const resp = await fetch(window.chatConfig.sendUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    const data = await safeReadJson(resp);
    if (!resp.ok || !data.success) {
      throw new Error(data.message || data.error || "发送失败");
    }

    currentTaskId = data.task_id;
    currentProjectId = data.project_id || currentProjectId;

    if (taskIdText) taskIdText.textContent = currentTaskId || "未返回";
    if (projectIdText && currentProjectId) projectIdText.textContent = currentProjectId;
    if (taskStatusText) taskStatusText.textContent = `${data.status || "pending"} / ${data.current_stage || "queued"}`;

    updateProgressCardFromTask(data);
    startPollingTask(currentTaskId);
  } catch (err) {
    console.error("发送失败：", err);
    addMessage("system", `发送失败：${err.message}`);
    if (sendBtn) sendBtn.disabled = false;
  }
}

function stopPolling() {
  if (pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
}

function startPollingTask(taskId) {
  stopPolling();

  const tick = async () => {
    try {
      const resp = await fetch(`${window.chatConfig.taskBaseUrl}${taskId}`);
      const data = await safeReadJson(resp);

      if (!resp.ok || !data.success) {
        throw new Error(data.message || "任务查询失败");
      }

      if (taskStatusText) {
        taskStatusText.textContent = `${data.status} / ${data.current_stage}`;
      }

      if (data.project_id) {
        currentProjectId = data.project_id;
        if (projectIdText) projectIdText.textContent = currentProjectId;
      }

      if (data.task_id && taskIdText) {
        taskIdText.textContent = data.task_id;
      }

      updateProgressCardFromTask(data);

      if (currentProjectId) {
        try {
          await refreshProjectPanels(currentProjectId);
          enableLegacyLinks(currentProjectId);
        } catch (panelErr) {
          console.warn("项目面板刷新失败：", panelErr);
          addMessage("system", `结果区刷新失败：${panelErr.message}`);
        }
      }

      updateSlowTip(data);

      if (data.status === "done") {
        stopPolling();
        if (sendBtn) sendBtn.disabled = false;
        addMessage("system", "最终稿已完成，你现在可以查看完整内容。");
        switchTab("final");
        return;
      }

      if (data.status === "failed") {
        stopPolling();
        if (sendBtn) sendBtn.disabled = false;
        addMessage("system", `任务失败：${data.error || "未知错误"}`);
      }
    } catch (err) {
      stopPolling();
      if (sendBtn) sendBtn.disabled = false;
      console.error("轮询失败：", err);
      addMessage("system", `轮询失败：${err.message}`);
    }
  };

  tick();
  pollingTimer = setInterval(tick, POLL_INTERVAL);
}

async function loadCurrentModel() {
  if (!window.chatConfig.modelCurrentUrl) return;
  try {
    const resp = await fetch(window.chatConfig.modelCurrentUrl);
    const data = await safeReadJson(resp);
    if (resp.ok && data.success) {
      const model = data.selected_model || "deepseek";
      if (modelSelect) modelSelect.value = model;
      if (currentModelText) currentModelText.textContent = model;
    }
  } catch (err) {
    console.error("加载当前模型失败：", err);
  }
}

async function updateModel(model) {
  if (!window.chatConfig.modelSelectUrl) return;
  try {
    const resp = await fetch(window.chatConfig.modelSelectUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ model })
    });
    const data = await safeReadJson(resp);
    if (!resp.ok || !data.success) {
      throw new Error(data.message || "模型切换失败");
    }
    if (currentModelText) currentModelText.textContent = data.selected_model;
  } catch (err) {
    alert(`模型切换失败：${err.message}`);
  }
}

function initSplitters() {
  const app = document.getElementById("chatApp");
  const leftSplitter = document.getElementById("leftSplitter");
  const rightSplitter = document.getElementById("rightSplitter");
  if (!app || !leftSplitter || !rightSplitter) return;

  let isDraggingLeft = false;
  let isDraggingRight = false;
  let leftWidth = 240;
  let rightWidth = 500;

  function applyLayout() {
    app.style.gridTemplateColumns = `${leftWidth}px 6px 1fr 6px ${rightWidth}px`;
  }

  leftSplitter.addEventListener("mousedown", () => {
    isDraggingLeft = true;
    leftSplitter.classList.add("dragging");
  });

  rightSplitter.addEventListener("mousedown", () => {
    isDraggingRight = true;
    rightSplitter.classList.add("dragging");
  });

  document.addEventListener("mouseup", () => {
    isDraggingLeft = false;
    isDraggingRight = false;
    leftSplitter.classList.remove("dragging");
    rightSplitter.classList.remove("dragging");
  });

  document.addEventListener("mousemove", (e) => {
    if (isDraggingLeft) {
      leftWidth = Math.max(190, Math.min(420, e.clientX));
      applyLayout();
    }
    if (isDraggingRight) {
      const totalWidth = window.innerWidth;
      rightWidth = Math.max(380, Math.min(820, totalWidth - e.clientX));
      applyLayout();
    }
  });

  applyLayout();
}

function updateEpisodeCounter(task) {
  if (!episodeCounterText) return;

  const total = Number(task.episode_count || 0);
  const done = Number(task.generated_episode_count || 0);

  if (getCurrentGranularity() !== "multi_episode_script" || !total) {
    episodeCounterText.textContent = "";
    return;
  }
  episodeCounterText.textContent = `当前已生成 ${done} 集，共 ${total} 集`;
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
    btn.classList.add("active");
    const target = document.getElementById(`tab-${btn.dataset.tab}`);
    if (target) target.classList.add("active");
  });
});

if (newChatBtn) {
  newChatBtn.addEventListener("click", resetChatState);
}

if (sendBtn) {
  sendBtn.addEventListener("click", handleSend);
}

if (modelSelect) {
  modelSelect.addEventListener("change", () => {
    updateModel(modelSelect.value);
  });
}

if (granularitySelect) {
  granularitySelect.addEventListener("change", () => {
    updateFinalTabLabel();
    setIdleProgressCard();
  });
}

window.addEventListener("DOMContentLoaded", () => {
  disableLegacyLinks();
  updateFinalTabLabel();
  setIdleProgressCard();
  loadCurrentModel();
  initSplitters();
});