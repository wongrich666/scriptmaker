let currentTaskId = null;
let currentProjectId = null;
let pollingTimer = null;

const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");

const messageInput = document.getElementById("messageInput");
const genreInput = document.getElementById("genreInput");
const styleInput = document.getElementById("styleInput");
const wordCountInput = document.getElementById("wordCountInput");
const referenceTextInput = document.getElementById("referenceTextInput");
const frameworkTextInput = document.getElementById("frameworkTextInput");
const bannedInput = document.getElementById("bannedInput");
const outputGranularityInput = document.getElementById("outputGranularityInput");

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
    // 旧页面降级为查看/编辑页：聊天页只负责跳转过去
    storyExportBtn.href = `/dashboard/script/${projectId}/export_story_txt`;
    scriptExportBtn.href = `/dashboard/script/${projectId}/export_script_txt`;
    editScriptBtn.href = `/dashboard/script/${projectId}/edit?tab=basic`;
    characterDetailBtn.href = `/dashboard/script/${projectId}/edit?tab=characters`;
    chapterDetailBtn.href = `/chapters/script/${projectId}/chapters?tab=chapters`;

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
        alert("请输入需求");
        return;
    }

    sendBtn.disabled = true;

    addMessage("user", message);
    addMessage("system", "正在创建任务，请稍候……");

    const payload = {
        project_id: currentProjectId,
        message: message,
        meta: {
            genre: genreInput.value.trim(),
            style: styleInput.value.trim(),
            word_count: wordCountInput.value.trim(),
            reference_text: referenceTextInput.value.trim(),
            framework_text: frameworkTextInput.value.trim(),
            banned: bannedInput.value.trim(),
            output_granularity: outputGranularityInput.value.trim() || "outline"
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
        taskIdText.textContent = currentTaskId;
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