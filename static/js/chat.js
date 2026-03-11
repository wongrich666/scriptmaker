const DEFAULT_WORD_COUNT_WAN = 2;

let currentTaskId = null;
let currentProjectId = null;
let pollingTimer = null;

let referenceTextState = "";
let referenceSourceType = "";
let referenceSourceName = "";

const toggleReferenceBtn = document.getElementById("toggleReferenceBtn");
const referencePanel = document.getElementById("referencePanel");

const referenceUrlInput = document.getElementById("referenceUrlInput");
const referenceFileInput = document.getElementById("referenceFileInput");
const ingestUrlBtn = document.getElementById("ingestUrlBtn");
const ingestFileBtn = document.getElementById("ingestFileBtn");

const referenceStatusText = document.getElementById("referenceStatusText");
const referencePreviewBox = document.getElementById("referencePreviewBox");
const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");

const messageInput = document.getElementById("messageInput");
const wordCountInput = document.getElementById("wordCountInput");

const projectIdText = document.getElementById("projectIdText");
const taskIdText = document.getElementById("taskIdText");
const taskStatusText = document.getElementById("taskStatusText");

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

document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    });
});

newChatBtn.addEventListener("click", resetChatState);
sendBtn.addEventListener("click", handleSend);

function resetChatState() {
    currentTaskId = null;
    currentProjectId = null;

    projectIdText.textContent = "未创建";
    taskIdText.textContent = "未开始";
    taskStatusText.textContent = "空闲";

    finalScriptBox.textContent = "暂无内容";
    characterBox.textContent = "暂无内容";
    outlineBox.textContent = "暂无内容";
    reviewBox.textContent = "暂无内容";
    traceBox.textContent = "暂无内容";

    disableLegacyLinks();

    if (pollingTimer) {
        clearInterval(pollingTimer);
        pollingTimer = null;
    }
}

function addMessage(role, text) {
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
        a.classList.add("disabled");
        a.href = "#";
    });
}

function enableLegacyLinks(projectId) {
    storyExportBtn.href = `/dashboard/script/${projectId}/export_story_txt`;
    scriptExportBtn.href = `/dashboard/script/${projectId}/export_script_txt`;
    editScriptBtn.href = `/dashboard/script/${projectId}/edit?tab=basic`;
    characterDetailBtn.href = `/dashboard/script/${projectId}/edit?tab=characters`;
    chapterDetailBtn.href = `/chapters/script/${projectId}/chapters`;

    [
        storyExportBtn,
        scriptExportBtn,
        editScriptBtn,
        characterDetailBtn,
        chapterDetailBtn
    ].forEach(a => a.classList.remove("disabled"));
}

async function handleSend() {
    const message = messageInput.value.trim();
    if (!message) {
        alert("请填写“用户输入”");
        return;
    }

    let wordCountWan = parseFloat(wordCountInput.value);
    if (Number.isNaN(wordCountWan) || wordCountWan <= 0) {
        wordCountWan = DEFAULT_WORD_COUNT_WAN;
        wordCountInput.value = DEFAULT_WORD_COUNT_WAN;
    }

    sendBtn.disabled = true;

    addMessage("user", `【字数】${wordCountWan}万字\n【需求】${message}`);
    addMessage("system", "正在创建任务，请稍候……");

    const payload = {
        project_id: currentProjectId,
        message: message,
        meta: {
            word_count_wan: wordCountWan,
            reference_text: referenceTextState,
            reference_source_type: referenceSourceType,
            reference_source_name: referenceSourceName
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

        const data = await resp.json();

        if (!resp.ok || !data.success) {
            throw new Error(data.message || data.error || "发送失败");
        }

        currentTaskId = data.task_id;
        taskIdText.textContent = data.task_id || "未返回";
        taskStatusText.textContent = data.status || "pending";

        startPollingTask(currentTaskId);
    } catch (err) {
        addMessage("system", `发送失败：${err.message}`);
        sendBtn.disabled = false;
    }
}

function startPollingTask(taskId) {
    if (pollingTimer) {
        clearInterval(pollingTimer);
    }

    pollingTimer = setInterval(async () => {
        try {
            const resp = await fetch(`${window.chatConfig.taskBaseUrl}${taskId}`);
            const data = await resp.json();

            if (!resp.ok || !data.success) {
                throw new Error(data.message || "任务查询失败");
            }

            taskStatusText.textContent = `${data.status} / ${data.current_stage}`;

            if (data.project_id) {
                currentProjectId = data.project_id;
                projectIdText.textContent = currentProjectId;
            }

            if (data.task_id) {
                taskIdText.textContent = data.task_id;
            }

            if (data.status === "done") {
                clearInterval(pollingTimer);
                pollingTimer = null;
                sendBtn.disabled = false;

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
                sendBtn.disabled = false;
                addMessage("system", `任务失败：${data.error || "未知错误"}`);
            }
        } catch (err) {
            clearInterval(pollingTimer);
            pollingTimer = null;
            sendBtn.disabled = false;
            addMessage("system", `轮询失败：${err.message}`);
        }
    }, 2000);
}

async function loadArtifacts(projectId) {
    const resp = await fetch(`${window.chatConfig.projectBaseUrl}${projectId}/artifacts`);
    const data = await resp.json();

    if (!resp.ok || !data.success) {
        throw new Error(data.message || "加载结果失败");
    }

    finalScriptBox.textContent = data.final_script || "暂无最终剧本";
    characterBox.textContent = data.character_bible || "暂无人物设定";
    outlineBox.textContent = data.plot_outline || "暂无剧情大纲";
    reviewBox.textContent = data.review_report || "暂无审核报告";
}

async function loadTrace(projectId) {
    const resp = await fetch(`${window.chatConfig.projectBaseUrl}${projectId}/trace`);
    const data = await resp.json();

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

    traceBox.textContent = traceText || "暂无生成过程";
}

toggleReferenceBtn.addEventListener("click", () => {
    referencePanel.classList.toggle("hidden");
});

document.querySelectorAll(".ref-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".ref-tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".ref-tab-content").forEach(c => c.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(`ref-tab-${btn.dataset.refTab}`).classList.add("active");
    });
});

ingestUrlBtn.addEventListener("click", ingestReferenceUrl);
ingestFileBtn.addEventListener("click", ingestReferenceFile);

async function ingestReferenceUrl() {
    const url = referenceUrlInput.value.trim();
    if (!url) {
        alert("请先输入网页链接");
        return;
    }

    referenceStatusText.textContent = "读取中...";
    referencePreviewBox.textContent = "正在抓取网页正文，请稍候...";

    try {
        const resp = await fetch("/api/reference/ingest", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                type: "url",
                url: url
            })
        });

        const data = await resp.json();
        if (!resp.ok || !data.success) {
            throw new Error(data.message || data.error || "网页读取失败");
        }

        referenceTextState = data.reference_text || "";
        referenceSourceType = "url";
        referenceSourceName = data.source_name || url;

        referenceStatusText.textContent = `已加载：${referenceSourceName}`;
        referencePreviewBox.textContent = referenceTextState || "未提取到正文";
    } catch (err) {
        referenceStatusText.textContent = "读取失败";
        referencePreviewBox.textContent = `错误：${err.message}`;
    }
}

async function ingestReferenceFile() {
    const file = referenceFileInput.files[0];
    if (!file) {
        alert("请先选择文件");
        return;
    }

    const formData = new FormData();
    formData.append("type", "file");
    formData.append("file", file);

    referenceStatusText.textContent = "读取中...";
    referencePreviewBox.textContent = "正在解析文件，请稍候...";

    try {
        const resp = await fetch("/api/reference/ingest", {
            method: "POST",
            body: formData
        });

        const data = await resp.json();
        if (!resp.ok || !data.success) {
            throw new Error(data.message || data.error || "文件读取失败");
        }

        referenceTextState = data.reference_text || "";
        referenceSourceType = "file";
        referenceSourceName = data.source_name || file.name;

        referenceStatusText.textContent = `已加载：${referenceSourceName}`;
        referencePreviewBox.textContent = referenceTextState || "未提取到正文";
    } catch (err) {
        referenceStatusText.textContent = "读取失败";
        referencePreviewBox.textContent = `错误：${err.message}`;
    }
}