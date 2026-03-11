const DEFAULT_WORD_COUNT_WAN = 2;

let currentTaskId = null;
let currentProjectId = null;
let pollingTimer = null;

const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");

const messageInput = document.getElementById("messageInput");
const wordCountInput = document.getElementById("wordCountInput");

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

// 标签切换
document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));

        btn.classList.add("active");
        const target = document.getElementById(`tab-${btn.dataset.tab}`);
        if (target) {
            target.classList.add("active");
        }
    });
});

// 绑定按钮
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

function resetChatState() {
    currentTaskId = null;
    currentProjectId = null;

    if (projectIdText) projectIdText.textContent = "未创建";
    if (taskIdText) taskIdText.textContent = "未开始";
    if (taskStatusText) taskStatusText.textContent = "空闲";

    if (finalScriptBox) finalScriptBox.textContent = "暂无内容";
    if (characterBox) characterBox.textContent = "暂无内容";
    if (outlineBox) outlineBox.textContent = "暂无内容";
    if (reviewBox) reviewBox.textContent = "暂无内容";
    if (traceBox) traceBox.textContent = "暂无内容";

    disableLegacyLinks();

    if (pollingTimer) {
        clearInterval(pollingTimer);
        pollingTimer = null;
    }
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
    [
        storyExportBtn,
        scriptExportBtn,
        editScriptBtn,
        characterDetailBtn,
        chapterDetailBtn
    ].forEach(a => {
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

    [
        storyExportBtn,
        scriptExportBtn,
        editScriptBtn,
        characterDetailBtn,
        chapterDetailBtn
    ].forEach(a => {
        if (!a) return;
        a.classList.remove("disabled");
    });
}

async function safeReadJson(resp) {
  const text = await resp.text();
  const contentType = resp.headers.get("content-type") || "";

  if (!contentType.includes("application/json")) {
    throw new Error(
      `接口没有返回 JSON。HTTP ${resp.status}，Content-Type: ${contentType}，前200字符：${text.slice(0, 200)}`
    );
  }

  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error(`JSON 解析失败：${e.message}；原始内容前200字符：${text.slice(0, 200)}`);
  }
}

async function handleSend() {
    const message = messageInput ? messageInput.value.trim() : "";
    if (!message) {
        alert("请填写“用户输入”");
        return;
    }

    let wordCountWan = wordCountInput ? parseFloat(wordCountInput.value) : DEFAULT_WORD_COUNT_WAN;
    if (Number.isNaN(wordCountWan) || wordCountWan <= 0) {
        wordCountWan = DEFAULT_WORD_COUNT_WAN;
        if (wordCountInput) wordCountInput.value = DEFAULT_WORD_COUNT_WAN;
    }

    if (sendBtn) sendBtn.disabled = true;

    addMessage("user", `【字数】${wordCountWan}万字\n【需求】${message}`);
    addMessage("system", "正在创建任务，请稍候……");

    const payload = {
        project_id: currentProjectId,
        message: message,
        meta: {
            word_count_wan: wordCountWan
        }
    };

    try {
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
        if (taskIdText) taskIdText.textContent = data.task_id || "未返回";
        if (taskStatusText) taskStatusText.textContent = data.status || "pending";

        startPollingTask(currentTaskId);
    } catch (err) {
        addMessage("system", `发送失败：${err.message}`);
        if (sendBtn) sendBtn.disabled = false;
    }
}

function startPollingTask(taskId) {
    if (pollingTimer) {
        clearInterval(pollingTimer);
    }

    pollingTimer = setInterval(async () => {
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

            if (data.status === "done") {
                clearInterval(pollingTimer);
                pollingTimer = null;
                if (sendBtn) sendBtn.disabled = false;

                addMessage("system", "任务已完成，正在加载结果……");

                if (currentProjectId) {
                    await loadArtifacts(currentProjectId);
                    await loadTrace(currentProjectId);
                    enableLegacyLinks(currentProjectId);
                }
            }

            if (data.status === "failed") {
                clearInterval(pollingTimer);
                pollingTimer = null;
                if (sendBtn) sendBtn.disabled = false;
                addMessage("system", `任务失败：${data.error || "未知错误"}`);
            }
        } catch (err) {
            clearInterval(pollingTimer);
            pollingTimer = null;
            if (sendBtn) sendBtn.disabled = false;
            addMessage("system", `轮询失败：${err.message}`);
        }
    }, 2000);
}

async function loadArtifacts(projectId) {
    const resp = await fetch(`${window.chatConfig.projectBaseUrl}${projectId}/artifacts`);
    const data = await safeReadJson(resp);

    if (!resp.ok || !data.success) {
        throw new Error(data.message || "加载结果失败");
    }

    if (finalScriptBox) finalScriptBox.textContent = data.final_script || "暂无最终剧本";
    if (characterBox) characterBox.textContent = data.character_bible || "暂无人物设定";
    if (outlineBox) outlineBox.textContent = data.plot_outline || "暂无剧情大纲";
    if (reviewBox) reviewBox.textContent = data.review_report || "暂无审核报告";
}

async function loadTrace(projectId) {
    const resp = await fetch(`${window.chatConfig.projectBaseUrl}${projectId}/trace`);
    const data = await safeReadJson(resp);

    if (!resp.ok || !data.success) {
        throw new Error(data.message || "加载过程失败");
    }

    const traceText = (data.trace || []).map((item, idx) => {
        return [
            `#${idx + 1}`,
            `阶段：${item.stage || ""}`,
            `时间：${item.time || ""}`,
            `摘要：${item.summary || ""}`,
            ""
        ].join("\n");
    }).join("\n");

    if (traceBox) traceBox.textContent = traceText || "暂无生成过程";
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
    let rightWidth = 440;

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
            leftWidth = Math.max(180, Math.min(420, e.clientX));
            applyLayout();
        }

        if (isDraggingRight) {
            const totalWidth = window.innerWidth;
            rightWidth = Math.max(320, Math.min(760, totalWidth - e.clientX));
            applyLayout();
        }
    });

    applyLayout();
}

window.addEventListener("DOMContentLoaded", () => {
    loadCurrentModel();
    initSplitters();
});