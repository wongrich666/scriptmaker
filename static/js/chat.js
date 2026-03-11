const DEFAULT_WORD_COUNT = "2万字以内（短篇）";

const MAIN_CATEGORIES = [
    "现代言情", "古代言情", "都市", "玄幻仙侠", "悬疑",
    "历史", "校园青春", "科幻末世", "奇幻", "职场", "衍生"
];

const THEME_TAGS = [
    "古言权谋", "悬疑恋爱", "纯爱", "衍生", "仕途", "综影视",
    "天灾", "第一人称", "赛博朋克", "第四天灾", "规则怪谈", "古代",
    "悬疑", "克苏鲁", "都市异能", "末日求生", "灵气复苏", "高武世界",
    "异世大陆", "东方玄幻", "谍战", "清朝", "宋朝", "断层"
];

const CHARACTER_TAGS = [
    "总裁", "多女主", "教授", "忠犬", "全能", "白切黑",
    "双学霸", "位尊权重", "作精", "大佬", "大小姐", "特工",
    "游戏主播", "神探", "宫廷侯爵", "皇帝", "将军", "毒医",
    "厨娘", "律师", "医生", "明星", "替身", "双面"
];

const PLOT_TAGS = [
    "女频悬疑", "西方奇幻", "东方仙侠", "古风世情", "科幻末世", "男频衍生",
    "女频衍生", "民国言情", "都市高武", "悬疑灵异", "悬疑脑洞", "抗战谍战",
    "青春甜宠", "双男主", "古言脑洞", "历史古代", "历史脑洞", "现言脑洞",
    "都市种田", "都市脑洞", "都市日常", "玄幻脑洞", "玄幻言情"
];

let currentTaskId = null;
let currentProjectId = null;
let pollingTimer = null;

const selectedMainCategories = new Set();
const selectedThemeTags = new Set();
const selectedCharacterTags = new Set();
const selectedPlotTags = new Set();

const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");

const messageInput = document.getElementById("messageInput");
const customStyleInput = document.getElementById("customStyleInput");
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

document.querySelectorAll(".subtab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".subtab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".style-tab-panel").forEach(p => p.classList.remove("active"));

        btn.classList.add("active");
        const panelId = `${btn.dataset.styleTab}TagContainer`;
        document.getElementById(panelId).classList.add("active");
    });
});

newChatBtn.addEventListener("click", resetChatState);
sendBtn.addEventListener("click", handleSend);

renderChips("mainCategoryContainer", MAIN_CATEGORIES, selectedMainCategories);
renderChips("themeTagContainer", THEME_TAGS, selectedThemeTags);
renderChips("characterTagContainer", CHARACTER_TAGS, selectedCharacterTags);
renderChips("plotTagContainer", PLOT_TAGS, selectedPlotTags);

function renderChips(containerId, dataList, selectedSet) {
    const container = document.getElementById(containerId);
    container.innerHTML = "";

    dataList.forEach(item => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip";
        chip.textContent = item;

        chip.addEventListener("click", () => {
            if (selectedSet.has(item)) {
                selectedSet.delete(item);
                chip.classList.remove("selected");
            } else {
                selectedSet.add(item);
                chip.classList.add("selected");
            }
        });

        container.appendChild(chip);
    });
}

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

function getStyleTagSummary() {
    const theme = Array.from(selectedThemeTags);
    const character = Array.from(selectedCharacterTags);
    const plot = Array.from(selectedPlotTags);
    return [...theme, ...character, ...plot];
}

async function handleSend() {
    const message = messageInput.value.trim();
    if (!message) {
        alert("请先填写‘剧本需求一句话’");
        return;
    }

    if (selectedMainCategories.size === 0) {
        alert("请至少选择一个主分类");
        return;
    }

    if (getStyleTagSummary().length === 0) {
        alert("请至少选择一个风格标签");
        return;
    }

    sendBtn.disabled = true;

    addMessage("user", message);
    addMessage("system", "正在创建任务，请稍候……");

    const wordCount = wordCountInput.value.trim() || DEFAULT_WORD_COUNT;
    const mainCategories = Array.from(selectedMainCategories);
    const themeTags = Array.from(selectedThemeTags);
    const characterTags = Array.from(selectedCharacterTags);
    const plotTags = Array.from(selectedPlotTags);
    const styleTags = getStyleTagSummary();

    const payload = {
        project_id: currentProjectId,
        message: message,
        meta: {
            word_count: wordCount,
            reference_text: referenceTextInput.value.trim(),
            framework_text: frameworkTextInput.value.trim(),
            banned: bannedInput.value.trim(),
            output_granularity: outputGranularityInput.value.trim() || "outline",

            // 新增：结构化多选
            main_categories: mainCategories,
            theme_tags: themeTags,
            character_tags: characterTags,
            plot_tags: plotTags,
            style_tags: styleTags,

            // 兼容旧字段
            genre: mainCategories.join("、"),
            style: [customStyleInput.value.trim(), ...styleTags].filter(Boolean).join("、")
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