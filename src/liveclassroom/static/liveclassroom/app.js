// src/protocol.ts
function csrfToken() {
  const cookie = document.cookie.match(/(?:^|;)\s*csrftoken=([^;]+)/)?.[1];
  if (cookie) {
    try {
      return decodeURIComponent(cookie);
    } catch {
      return cookie;
    }
  }
  return document.querySelector("input[name=csrfmiddlewaretoken]")?.value ?? "";
}
async function getJson(url) {
  const response = await fetch(url, { credentials: "same-origin" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(payload.detail ?? "Request failed");
  return payload;
}
async function postJson(url, body = {}, idempotencyKey) {
  const headers = {
    "Content-Type": "application/json",
    "X-CSRFToken": csrfToken()
  };
  if (idempotencyKey)
    headers["Idempotency-Key"] = idempotencyKey;
  const response = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: JSON.stringify(body)
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(payload.detail ?? "Request failed");
  return payload;
}
async function putJson(url, body = {}, idempotencyKey) {
  const headers = {
    "Content-Type": "application/json",
    "X-CSRFToken": csrfToken()
  };
  if (idempotencyKey)
    headers["Idempotency-Key"] = idempotencyKey;
  const response = await fetch(url, {
    method: "PUT",
    credentials: "same-origin",
    headers,
    body: JSON.stringify(body)
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(payload.detail ?? "Request failed");
  return payload;
}
async function deleteJson(url, idempotencyKey) {
  const headers = {
    "Content-Type": "application/json",
    "X-CSRFToken": csrfToken()
  };
  if (idempotencyKey)
    headers["Idempotency-Key"] = idempotencyKey;
  const response = await fetch(url, {
    method: "DELETE",
    credentials: "same-origin",
    headers
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(payload.detail ?? "Request failed");
  return payload;
}
function apiEndpoint(stateUrl, resource) {
  const url = new URL(stateUrl, window.location.href);
  const statePath = /^(.*\/sessions\/)(\d+)\/state\/?$/;
  const match = url.pathname.match(statePath);
  if (!match)
    throw new Error("Unsupported classroom state URL.");
  const resourcePath = resource.replace(/^\/+/, "").replace(/\/+$/, "");
  if (resourcePath.startsWith("sessions/")) {
    url.pathname = `${match[1]}${match[2]}/${resourcePath.slice("sessions/".length)}/`;
  } else {
    url.pathname = `${match[1].replace(/sessions\/$/, "")}${resourcePath}/`;
  }
  url.search = "";
  return url.toString();
}
function websocketUrl(path) {
  if (/^wss?:\/\//i.test(path))
    return path;
  return `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}${path}`;
}

// src/locales.ts
var translations = {
  en: {
    activity: "Activity",
    waiting: "Waiting for the teacher.",
    unavailable: "Classroom state is unavailable.",
    state: "State",
    revision: "revision",
    save: "Save",
    cancel: "Cancel",
    delete: "Delete",
    loading: "Loading…",
    updated: "Updated",
    language: "Language",
    english: "English",
    chinese: "简体中文",
    submit: "Submit answer",
    update: "Update answer",
    saved: "Answer saved.",
    stale: "This activity changed. Review and submit again.",
    noAnswer: "This item does not require a response.",
    notShownYet: "The teacher has not shown this activity yet.",
    waitingAdmission: "Waiting for teacher admission.",
    joinClassroom: "Join classroom",
    displayName: "Display name",
    enterDisplayName: "Enter a display name to join this classroom.",
    signInRequired: "Sign in to join this classroom.",
    history: "Previous activities",
    noHistory: "No previous activities are available.",
    historyUnavailable: "Activity history is unavailable.",
    start: "Start classroom",
    pause: "Pause",
    end: "End classroom",
    confirmEnd: "End this classroom? Students will no longer be able to join.",
    close: "Close answers",
    reveal: "Reveal answer",
    publish: "Publish",
    display: "Display",
    participants: "Participants",
    displayPreview: "Display preview",
    participantPreview: "Student preview",
    noActivityPublished: "No activity published.",
    controls: "Classroom controls",
    audienceVisibility: "Audience visibility",
    showPrompt: "Show prompt",
    showAggregate: "Show aggregate",
    showAnswer: "Show answer",
    showExplanation: "Show explanation",
    showOwnStatus: "Show response status",
    allowReview: "Allow review",
    admit: "Admit",
    pending: "pending",
    chat: "Class chat",
    chatDisabled: "Chat is disabled.",
    chatUnavailable: "Chat is unavailable.",
    send: "Send",
    enableChat: "Enable chat",
    noMessages: "No messages yet.",
    analyticsSummary: "Analytics summary",
    analyticsUnavailable: "Analytics are unavailable.",
    responses: "Responses",
    noResponses: "No responses yet.",
    publishToReview: "Publish an activity to review responses.",
    responseRate: "Response rate",
    admitted: "admitted",
    connected: "connected",
    attended: "attended",
    results: "Results",
    wordFrequencies: "Word frequencies",
    moderation: "Moderation",
    singleChoice: "Single choice",
    multipleChoice: "Multiple choice",
    trueFalse: "True / False",
    poll: "Poll",
    shortText: "Short text",
    numeric: "Numeric",
    rating: "Rating",
    ranking: "Ranking",
    wordCloud: "Word cloud",
    markdownContent: "Markdown content",
    mediaContent: "Media content",
    timer: "Timer",
    timerRemaining: "Time remaining",
    timerFinished: "Time's up!",
    seconds: "s",
    votes: "votes",
    vote: "vote",
    offline: "Offline",
    notConnected: "Not connected",
    builderTitle: "Visual Flow Builder",
    flows: "Flows",
    createFlow: "Create flow",
    flowTitle: "Flow title",
    flowDescription: "Description (optional)",
    steps: "Flow steps",
    addStep: "Add step",
    reorderSteps: "Reorder steps",
    moveUp: "Move up",
    moveDown: "Move down",
    removeStep: "Remove step",
    duplicateFlow: "Duplicate flow",
    saveSessionAsFlow: "Save session as flow",
    saveAsFlowPrompt: "Enter title for the new flow:",
    importContent: "Import content",
    importJson: "Import JSON",
    importMarkdown: "Import Markdown / YAML",
    importButton: "Import",
    importSuccess: "Content imported successfully.",
    importError: "Import failed:",
    livePreview: "Live preview",
    selectFlow: "Select a flow to edit",
    noStepsYet: "No steps in this flow yet. Add an activity step or import content.",
    launchToClassroom: "Launch to live class",
    launchedSuccess: "Launched to classroom!",
    aiAssistant: "AI Authoring Assistant",
    aiModel: "Model",
    aiThread: "Conversation",
    newThread: "New conversation",
    threadTitle: "Conversation title",
    createThread: "Start",
    aiPromptPlaceholder: "Ask the AI assistant to draft a quiz, refine questions, or summarize content…",
    aiSend: "Ask AI",
    aiGenerating: "Generating draft…",
    aiDraftReady: "Draft suggestion ready",
    aiInsertToBuilder: "Insert into flow",
    aiCopy: "Copy text",
    aiCopied: "Copied!",
    aiAttachments: "Attached context",
    attachCurrentStep: "Attach current step",
    noAttachments: "No attached context",
    aiNote: "AI suggestions never publish automatically. Review before using.",
    stepType: "Activity type",
    promptLabel: "Prompt / Question",
    optionsLabel: "Options (one per line)",
    correctAnswer: "Correct answer(s)",
    explanation: "Explanation",
    markdownContentLabel: "Markdown text",
    mediaUrlLabel: "Media URL",
    mediaTypeLabel: "Media type",
    captionLabel: "Caption",
    durationSecondsLabel: "Duration (seconds)",
    validationError: "Please fill in all required fields.",
    saveStep: "Save step",
    cancelStep: "Cancel",
    confirmDeleteStep: "Are you sure you want to remove this step?",
    confirmDuplicate: "Duplicate flow",
    copySuccess: "Copied!",
    previewHeading: "Live Preview",
    hidePreview: "Hide preview",
    showPreview: "Preview",
    toggleAi: "AI Assistant",
    stopWordsLabel: "Stop words (comma-separated, optional)",
    maxLengthLabel: "Max length (optional)",
    numericMinLabel: "Minimum value (optional)",
    numericMaxLabel: "Maximum value (optional)",
    numericStepLabel: "Step value (optional)",
    toggleSidebar: "Toggle AI Assistant",
    flowUpdated: "Flow updated successfully.",
    stepAdded: "Step added successfully.",
    stepDeleted: "Step removed successfully.",
    stepsReordered: "Steps reordered successfully.",
    importPlaceholder: "Paste JSON or Markdown/YAML here…",
    formatLabel: "Format",
    autoDetect: "Auto-detect",
    newFlowPrompt: "Enter flow title:",
    duplicateFlowPrompt: "Enter title for the duplicated flow:"
  },
  "zh-Hans": {
    activity: "课堂活动",
    waiting: "等待教师发布内容。",
    unavailable: "课堂状态不可用。",
    state: "状态",
    revision: "版本",
    save: "保存",
    cancel: "取消",
    delete: "删除",
    loading: "加载中…",
    updated: "已更新",
    language: "语言",
    english: "English",
    chinese: "简体中文",
    submit: "提交答案",
    update: "更新答案",
    saved: "答案已保存。",
    stale: "该活动已更新，请查看并重新提交。",
    noAnswer: "该内容无需作答。",
    notShownYet: "教师暂未显示该题目内容。",
    waitingAdmission: "等待教师准入审核。",
    joinClassroom: "加入课堂",
    displayName: "昵称 / 姓名",
    enterDisplayName: "请输入昵称加入该课堂。",
    signInRequired: "请登录后加入该课堂。",
    history: "历史活动",
    noHistory: "暂无历史活动。",
    historyUnavailable: "历史活动不可用。",
    start: "开始课堂",
    pause: "暂停课堂",
    end: "结束课堂",
    confirmEnd: "确认结束本课堂吗？结束后学生将无法继续加入。",
    close: "结束作答",
    reveal: "公布答案",
    publish: "发布",
    display: "投影大屏幕",
    participants: "学生端",
    displayPreview: "大屏预览",
    participantPreview: "学生预览",
    noActivityPublished: "暂无已发布的活动。",
    controls: "课堂控制",
    audienceVisibility: "受众可见性设置",
    showPrompt: "显示题目",
    showAggregate: "显示统计结果",
    showAnswer: "显示正确答案",
    showExplanation: "显示解析",
    showOwnStatus: "显示作答状态",
    allowReview: "允许回顾",
    admit: "准入",
    pending: "待审核",
    chat: "课堂讨论",
    chatDisabled: "讨论区已关闭。",
    chatUnavailable: "讨论区不可用。",
    send: "发送",
    enableChat: "开启讨论区",
    noMessages: "暂无发言。",
    analyticsSummary: "课堂数据概览",
    analyticsUnavailable: "统计数据不可用。",
    responses: "作答详情",
    noResponses: "暂无作答。",
    publishToReview: "发布活动后可在此查看学生作答。",
    responseRate: "作答率",
    admitted: "已准入",
    connected: "在线",
    attended: "总出勤",
    results: "统计结果",
    wordFrequencies: "词频统计",
    moderation: "作答审核",
    singleChoice: "单选题",
    multipleChoice: "多选题",
    trueFalse: "判断题",
    poll: "投票调研",
    shortText: "简答题",
    numeric: "数值题",
    rating: "评分题",
    ranking: "排序题",
    wordCloud: "词云互动",
    markdownContent: "Markdown 内容",
    mediaContent: "多媒体展示",
    timer: "计时器",
    timerRemaining: "剩余时间",
    timerFinished: "时间到！",
    seconds: "秒",
    votes: "票",
    vote: "票",
    offline: "离线",
    notConnected: "未连接",
    builderTitle: "教学流程可视化编辑器",
    flows: "教学流程列表",
    createFlow: "新建流程",
    flowTitle: "流程标题",
    flowDescription: "描述（选填）",
    steps: "流程步骤",
    addStep: "添加活动步骤",
    reorderSteps: "调整顺序",
    moveUp: "上移",
    moveDown: "下移",
    removeStep: "移除步骤",
    duplicateFlow: "复制流程",
    saveSessionAsFlow: "将当前课堂保存为流程",
    saveAsFlowPrompt: "请输入新流程的标题：",
    importContent: "导入教学内容",
    importJson: "导入 JSON",
    importMarkdown: "导入 Markdown / YAML",
    importButton: "开始导入",
    importSuccess: "内容导入成功。",
    importError: "导入失败：",
    livePreview: "实时预览",
    selectFlow: "选择要编辑的流程",
    noStepsYet: "本流程暂无步骤。请添加活动步骤或导入内容。",
    launchToClassroom: "直接推送到当前课堂",
    launchedSuccess: "已推送到课堂！",
    aiAssistant: "AI 课件助手",
    aiModel: "模型选择",
    aiThread: "对话主题",
    newThread: "新建对话",
    threadTitle: "主题名称",
    createThread: "开始对话",
    aiPromptPlaceholder: "向 AI 助手提问，例如：生成一组生物信息单选题、润色解析或总结课件…",
    aiSend: "发送提问",
    aiGenerating: "正在生成草稿…",
    aiDraftReady: "AI 建议草稿已生成",
    aiInsertToBuilder: "填入流程",
    aiCopy: "复制内容",
    aiCopied: "已复制！",
    aiAttachments: "已关联课件上下文",
    attachCurrentStep: "关联当前活动步骤",
    noAttachments: "未关联上下文",
    aiNote: "AI 生成内容仅作参考，绝不会自动发布或覆盖课堂内容。",
    stepType: "活动类型",
    promptLabel: "题目 / 提示语",
    optionsLabel: "选项（每行一个）",
    correctAnswer: "正确答案",
    explanation: "解析",
    markdownContentLabel: "Markdown 内容",
    mediaUrlLabel: "多媒体 URL",
    mediaTypeLabel: "媒体类型",
    captionLabel: "说明文字",
    durationSecondsLabel: "倒计时时长（秒）",
    validationError: "请填写所有必填字段。",
    saveStep: "保存步骤",
    cancelStep: "取消",
    confirmDeleteStep: "确认要移除该步骤吗？",
    confirmDuplicate: "复制教学流程",
    copySuccess: "已复制！",
    previewHeading: "实时预览",
    hidePreview: "隐藏预览",
    showPreview: "预览",
    toggleAi: "AI 助手",
    stopWordsLabel: "停用词（逗号分隔，选填）",
    maxLengthLabel: "最大字数限制（选填）",
    numericMinLabel: "最小值（选填）",
    numericMaxLabel: "最大值（选填）",
    numericStepLabel: "步长（选填）",
    toggleSidebar: "切换 AI 助手面板",
    flowUpdated: "流程更新成功。",
    stepAdded: "步骤添加成功。",
    stepDeleted: "步骤移除成功。",
    stepsReordered: "顺序调整成功。",
    importPlaceholder: "在此粘贴 JSON 或 Markdown/YAML 内容…",
    formatLabel: "格式",
    autoDetect: "自动识别",
    newFlowPrompt: "请输入流程标题：",
    duplicateFlowPrompt: "请输入复制后的流程标题："
  }
};
function getLocale(root) {
  if (root?.dataset.locale === "zh-Hans" || root?.dataset.locale === "zh")
    return "zh-Hans";
  if (root?.dataset.locale === "en")
    return "en";
  if (typeof window !== "undefined") {
    const urlParam = new URLSearchParams(window.location.search).get("lang");
    if (urlParam?.toLowerCase().startsWith("zh"))
      return "zh-Hans";
    if (urlParam?.toLowerCase().startsWith("en"))
      return "en";
    const stored = window.localStorage.getItem("liveclassroom_locale");
    if (stored === "zh-Hans" || stored === "zh")
      return "zh-Hans";
    if (stored === "en")
      return "en";
    const docLang = document.documentElement.lang;
    if (docLang && docLang.toLowerCase().startsWith("zh"))
      return "zh-Hans";
    if (docLang && docLang.toLowerCase().startsWith("en"))
      return "en";
  }
  return "en";
}
function setStoredLocale(locale) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem("liveclassroom_locale", locale);
    document.documentElement.lang = locale === "zh-Hans" ? "zh-CN" : "en";
  }
}
function t(key, locale) {
  const activeLocale = locale ?? getLocale();
  return translations[activeLocale][key] ?? translations.en[key] ?? String(key);
}
function mountLanguageSwitcher(root, onLocaleChange) {
  let switchBtn = root.querySelector(".lc-lang-switch");
  if (!switchBtn) {
    switchBtn = document.createElement("button");
    switchBtn.type = "button";
    switchBtn.className = "lc-lang-switch";
    switchBtn.setAttribute("aria-label", "Switch language / 切换语言");
    root.prepend(switchBtn);
  }
  const currentLocale = getLocale(root);
  switchBtn.setAttribute("data-current-locale", currentLocale);
  switchBtn.title = currentLocale === "zh-Hans" ? "Switch to English" : "切换为简体中文";
  switchBtn.innerHTML = currentLocale === "zh-Hans" ? '<span class="lc-lang-opt">EN</span> / <span class="lc-lang-opt lc-lang-curr">中文</span>' : '<span class="lc-lang-opt lc-lang-curr">EN</span> / <span class="lc-lang-opt">中文</span>';
  if (switchBtn.dataset.liveclassroomBound !== "true") {
    switchBtn.dataset.liveclassroomBound = "true";
    switchBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const current = getLocale(root);
      const nextLocale = current === "zh-Hans" ? "en" : "zh-Hans";
      setStoredLocale(nextLocale);
      root.dataset.locale = nextLocale;
      mountLanguageSwitcher(root, onLocaleChange);
      if (onLocaleChange) {
        onLocaleChange(nextLocale);
      }
    });
  }
  return switchBtn;
}

// src/ai_chat.ts
function mountAiChat(container, options = {}) {
  let isMounted = true;
  let activeThreadId = null;
  let activeJobId = null;
  let pollTimeout = null;
  let isGenerating = false;
  let models = [];
  let threads = [];
  let messages = [];
  container.replaceChildren();
  const root = document.createElement("div");
  root.className = "lc-ai-chat";
  container.append(root);
  const header = document.createElement("div");
  header.className = "lc-ai-header";
  const titleRow = document.createElement("div");
  titleRow.className = "lc-ai-title-row";
  const heading = document.createElement("h3");
  heading.textContent = t("aiAssistant", options.locale);
  titleRow.append(heading);
  const newThreadBtn = document.createElement("button");
  newThreadBtn.type = "button";
  newThreadBtn.className = "lc-btn-sm";
  newThreadBtn.textContent = `+ ${t("newThread", options.locale)}`;
  newThreadBtn.addEventListener("click", () => void handleCreateThread());
  titleRow.append(newThreadBtn);
  header.append(titleRow);
  const controlsRow = document.createElement("div");
  controlsRow.className = "lc-ai-controls";
  const threadGroup = document.createElement("div");
  threadGroup.className = "lc-ai-control-group";
  const threadLabel = document.createElement("label");
  threadLabel.textContent = `${t("aiThread", options.locale)}: `;
  const threadSelect = document.createElement("select");
  threadSelect.className = "lc-ai-select";
  threadSelect.addEventListener("change", () => {
    const id = parseInt(threadSelect.value, 10);
    if (!Number.isNaN(id) && id !== activeThreadId) {
      selectThread(id);
    }
  });
  threadLabel.append(threadSelect);
  threadGroup.append(threadLabel);
  controlsRow.append(threadGroup);
  const modelGroup = document.createElement("div");
  modelGroup.className = "lc-ai-control-group";
  const modelLabel = document.createElement("label");
  modelLabel.textContent = `${t("aiModel", options.locale)}: `;
  const modelSelect = document.createElement("select");
  modelSelect.className = "lc-ai-select";
  modelLabel.append(modelSelect);
  modelGroup.append(modelLabel);
  controlsRow.append(modelGroup);
  header.append(controlsRow);
  root.append(header);
  const messagesContainer = document.createElement("div");
  messagesContainer.className = "lc-ai-messages";
  messagesContainer.setAttribute("role", "log");
  messagesContainer.setAttribute("aria-live", "polite");
  root.append(messagesContainer);
  const composer = document.createElement("div");
  composer.className = "lc-ai-composer";
  const attachmentBar = document.createElement("div");
  attachmentBar.className = "lc-ai-attachment-bar";
  const attachCheckbox = document.createElement("input");
  attachCheckbox.type = "checkbox";
  attachCheckbox.id = `lc-attach-ctx-${Math.random().toString(36).slice(2, 7)}`;
  attachCheckbox.checked = true;
  const attachLabel = document.createElement("label");
  attachLabel.htmlFor = attachCheckbox.id;
  attachLabel.textContent = ` ${t("attachCurrentStep", options.locale)}`;
  const attachBadge = document.createElement("span");
  attachBadge.className = "lc-ai-attachment-badge";
  attachBadge.textContent = t("noAttachments", options.locale);
  attachmentBar.append(attachCheckbox, attachLabel, attachBadge);
  composer.append(attachmentBar);
  const promptInput = document.createElement("textarea");
  promptInput.className = "lc-ai-input";
  promptInput.rows = 3;
  promptInput.placeholder = t("aiPromptPlaceholder", options.locale);
  promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSendMessage();
    }
  });
  composer.append(promptInput);
  const footerRow = document.createElement("div");
  footerRow.className = "lc-ai-footer";
  const noteText = document.createElement("small");
  noteText.className = "lc-ai-note";
  noteText.textContent = t("aiNote", options.locale);
  const actionGroup = document.createElement("div");
  actionGroup.className = "lc-ai-action-group";
  const statusText = document.createElement("span");
  statusText.className = "lc-ai-status";
  const sendButton = document.createElement("button");
  sendButton.type = "button";
  sendButton.className = "lc-ai-send-btn";
  sendButton.textContent = t("aiSend", options.locale);
  sendButton.addEventListener("click", () => void handleSendMessage());
  actionGroup.append(statusText, sendButton);
  footerRow.append(noteText, actionGroup);
  composer.append(footerRow);
  root.append(composer);
  function updateAttachmentInfo() {
    if (!options.getAttachment) {
      attachmentBar.style.display = "none";
      return;
    }
    const att = options.getAttachment();
    if (att) {
      attachBadge.textContent = att.title ? `${att.source_type}: ${att.title}` : `${att.source_type} #${att.source_id}`;
      attachBadge.className = "lc-ai-attachment-badge lc-ai-attachment-active";
      attachCheckbox.disabled = false;
    } else {
      attachBadge.textContent = t("noAttachments", options.locale);
      attachBadge.className = "lc-ai-attachment-badge";
      attachCheckbox.disabled = true;
    }
  }
  function renderMessages() {
    messagesContainer.replaceChildren();
    if (messages.length === 0) {
      const emptyNotice = document.createElement("p");
      emptyNotice.className = "lc-ai-empty";
      emptyNotice.textContent = t("noMessages", options.locale);
      messagesContainer.append(emptyNotice);
      return;
    }
    for (const msg of messages) {
      const msgCard = document.createElement("div");
      msgCard.className = `lc-ai-message lc-ai-message-${msg.role}`;
      const msgHeader = document.createElement("div");
      msgHeader.className = "lc-ai-msg-header";
      const authorSpan = document.createElement("strong");
      authorSpan.textContent = msg.role === "assistant" ? "AI Assistant" : "Teacher";
      msgHeader.append(authorSpan);
      if (msg.model_identifier) {
        const modelBadge = document.createElement("small");
        modelBadge.className = "lc-ai-msg-model";
        modelBadge.textContent = ` (${msg.model_identifier})`;
        msgHeader.append(modelBadge);
      }
      msgCard.append(msgHeader);
      const msgContent = document.createElement("div");
      msgContent.className = "lc-ai-msg-body";
      msgContent.textContent = msg.content;
      msgCard.append(msgContent);
      if (msg.role === "assistant" && msg.content.trim()) {
        const actionsRow = document.createElement("div");
        actionsRow.className = "lc-ai-msg-actions";
        const copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.className = "lc-btn-sm lc-btn-outline";
        copyBtn.textContent = t("aiCopy", options.locale);
        copyBtn.addEventListener("click", () => {
          if (navigator.clipboard?.writeText) {
            navigator.clipboard.writeText(msg.content).then(() => {
              copyBtn.textContent = t("aiCopied", options.locale);
              setTimeout(() => {
                copyBtn.textContent = t("aiCopy", options.locale);
              }, 2000);
            });
          }
        });
        actionsRow.append(copyBtn);
        if (options.onInsertDraft) {
          const insertBtn = document.createElement("button");
          insertBtn.type = "button";
          insertBtn.className = "lc-btn-sm lc-btn-primary";
          insertBtn.textContent = t("aiInsertToBuilder", options.locale);
          insertBtn.addEventListener("click", () => {
            options.onInsertDraft?.(msg.content);
          });
          actionsRow.append(insertBtn);
        }
        msgCard.append(actionsRow);
      }
      messagesContainer.append(msgCard);
    }
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }
  async function loadModels() {
    try {
      const data = await getJson("/api/v1/authoring/models/");
      models = data.models ?? [];
      modelSelect.replaceChildren();
      if (models.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No models available";
        modelSelect.append(opt);
        modelSelect.disabled = true;
      } else {
        modelSelect.disabled = false;
        for (const m of models) {
          const opt = document.createElement("option");
          opt.value = `${m.backend_key}:${m.identifier}`;
          opt.textContent = m.label || `${m.backend_key} (${m.identifier})`;
          modelSelect.append(opt);
        }
      }
    } catch {
      modelSelect.replaceChildren();
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Model discovery unavailable";
      modelSelect.append(opt);
      modelSelect.disabled = true;
    }
  }
  async function loadThreads() {
    try {
      const data = await getJson("/api/v1/authoring/threads/");
      threads = data.threads ?? [];
      threadSelect.replaceChildren();
      if (threads.length === 0) {
        const created = await postJson("/api/v1/authoring/threads/", {
          title: "Authoring Assistant"
        });
        threads = [created];
      }
      for (const th of threads) {
        const opt = document.createElement("option");
        opt.value = String(th.id);
        opt.textContent = th.title;
        threadSelect.append(opt);
      }
      if (!activeThreadId && threads.length > 0) {
        await selectThread(threads[0].id);
      } else if (activeThreadId) {
        threadSelect.value = String(activeThreadId);
      }
    } catch (err) {
      statusText.textContent = err instanceof Error ? err.message : "Failed to load threads";
    }
  }
  async function selectThread(threadId) {
    activeThreadId = threadId;
    threadSelect.value = String(threadId);
    try {
      statusText.textContent = t("loading", options.locale);
      const data = await getJson(`/api/v1/authoring/threads/${threadId}/`);
      messages = data.messages ?? [];
      renderMessages();
      statusText.textContent = "";
      const activeJob = (data.jobs ?? []).find((j) => j.status === "queued" || j.status === "running");
      if (activeJob) {
        pollJob(activeJob.id, threadId);
      }
    } catch (err) {
      statusText.textContent = err instanceof Error ? err.message : "Failed to load thread";
    }
  }
  async function handleCreateThread() {
    const title = window.prompt(t("newFlowPrompt", options.locale), "Lesson helper");
    if (!title || !title.trim())
      return;
    try {
      statusText.textContent = t("loading", options.locale);
      const created = await postJson("/api/v1/authoring/threads/", {
        title: title.trim()
      });
      threads.unshift(created);
      const opt = document.createElement("option");
      opt.value = String(created.id);
      opt.textContent = created.title;
      threadSelect.prepend(opt);
      await selectThread(created.id);
      statusText.textContent = "";
    } catch (err) {
      statusText.textContent = err instanceof Error ? err.message : "Failed to create conversation";
    }
  }
  function pollJob(jobId, threadId, attempt = 0) {
    if (!isMounted || attempt > 60) {
      isGenerating = false;
      sendButton.disabled = false;
      statusText.textContent = "";
      return;
    }
    isGenerating = true;
    activeJobId = jobId;
    sendButton.disabled = true;
    statusText.textContent = t("aiGenerating", options.locale);
    pollTimeout = window.setTimeout(async () => {
      try {
        const job = await getJson(`/api/v1/authoring/jobs/${jobId}/`);
        if (job.status === "succeeded") {
          isGenerating = false;
          sendButton.disabled = false;
          statusText.textContent = "";
          activeJobId = null;
          if (activeThreadId === threadId) {
            await selectThread(threadId);
          }
        } else if (job.status === "failed") {
          isGenerating = false;
          sendButton.disabled = false;
          statusText.textContent = job.error_code ? `AI error: ${job.error_code}` : "Generation failed.";
          activeJobId = null;
        } else {
          pollJob(jobId, threadId, attempt + 1);
        }
      } catch {
        isGenerating = false;
        sendButton.disabled = false;
        statusText.textContent = "AI job polling error";
        activeJobId = null;
      }
    }, 1000);
  }
  async function handleSendMessage() {
    const text = promptInput.value.trim();
    if (!text || isGenerating || !activeThreadId)
      return;
    const selectedModelVal = modelSelect.value;
    const [backend_key, model_identifier] = selectedModelVal ? selectedModelVal.split(":") : ["", ""];
    if (!backend_key || !model_identifier) {
      statusText.textContent = "Please select an AI model";
      return;
    }
    const attachments = [];
    if (attachCheckbox.checked && options.getAttachment) {
      const att = options.getAttachment();
      if (att && att.source_type && att.source_id) {
        attachments.push({
          source_type: att.source_type,
          source_id: att.source_id
        });
      }
    }
    try {
      isGenerating = true;
      sendButton.disabled = true;
      statusText.textContent = t("aiGenerating", options.locale);
      const res = await postJson(`/api/v1/authoring/threads/${activeThreadId}/messages/`, {
        content: text,
        backend_key,
        model_identifier,
        attachments
      });
      promptInput.value = "";
      if (res.message) {
        messages.push(res.message);
        renderMessages();
      }
      if (res.job?.id) {
        pollJob(res.job.id, activeThreadId);
      } else {
        isGenerating = false;
        sendButton.disabled = false;
        statusText.textContent = "";
      }
    } catch (err) {
      isGenerating = false;
      sendButton.disabled = false;
      statusText.textContent = err instanceof Error ? err.message : "Failed to send message";
    }
  }
  (async () => {
    await loadModels();
    await loadThreads();
    updateAttachmentInfo();
  })();
  const attachmentInterval = window.setInterval(updateAttachmentInfo, 2000);
  return {
    unmount: () => {
      isMounted = false;
      if (pollTimeout)
        clearTimeout(pollTimeout);
      clearInterval(attachmentInterval);
    },
    refreshThreads: loadThreads
  };
}

// src/builder.ts
var ACTIVITY_TYPES = [
  { type_key: "liveclassroom.single_choice", labelKey: "singleChoice" },
  { type_key: "liveclassroom.multiple_choice", labelKey: "multipleChoice" },
  { type_key: "liveclassroom.true_false", labelKey: "trueFalse" },
  { type_key: "liveclassroom.poll", labelKey: "poll" },
  { type_key: "liveclassroom.short_text", labelKey: "shortText" },
  { type_key: "liveclassroom.numeric", labelKey: "numeric" },
  { type_key: "liveclassroom.rating", labelKey: "rating" },
  { type_key: "liveclassroom.ranking", labelKey: "ranking" },
  { type_key: "liveclassroom.word_cloud", labelKey: "wordCloud" },
  { type_key: "liveclassroom.timer", labelKey: "timer" },
  { type_key: "liveclassroom.markdown", labelKey: "markdownContent" },
  { type_key: "liveclassroom.media", labelKey: "mediaContent" }
];
function mountBuilder(container) {
  const locale = getLocale(container);
  const rootDataset = container.dataset;
  let sessionId = null;
  if (rootDataset.sessionId) {
    sessionId = parseInt(rootDataset.sessionId, 10) || null;
  }
  if (!sessionId && typeof window !== "undefined") {
    const param = new URLSearchParams(window.location.search).get("session_id");
    if (param)
      sessionId = parseInt(param, 10) || null;
  }
  let activeFlowId = null;
  if (rootDataset.flowId) {
    activeFlowId = parseInt(rootDataset.flowId, 10) || null;
  }
  if (!activeFlowId && typeof window !== "undefined") {
    const param = new URLSearchParams(window.location.search).get("flow_id");
    if (param)
      activeFlowId = parseInt(param, 10) || null;
  }
  let flows = [];
  let currentFlow = null;
  const previewOpenSteps = new Set;
  let isAiSidebarOpen = true;
  let isAddStepOpen = false;
  container.replaceChildren();
  const root = document.createElement("div");
  root.className = "lc-builder-root";
  container.append(root);
  mountLanguageSwitcher(container, (nextLocale) => {
    container.dataset.locale = nextLocale;
    mountBuilder(container);
  });
  const layout = document.createElement("div");
  layout.className = "lc-builder-layout";
  root.append(layout);
  const mainPane = document.createElement("div");
  mainPane.className = "lc-builder-main";
  layout.append(mainPane);
  const sidebarPane = document.createElement("div");
  sidebarPane.className = "lc-builder-sidebar";
  layout.append(sidebarPane);
  const topBar = document.createElement("div");
  topBar.className = "lc-builder-topbar";
  const titleGroup = document.createElement("div");
  titleGroup.className = "lc-builder-title-group";
  const pageTitle = document.createElement("h2");
  pageTitle.textContent = t("builderTitle", locale);
  titleGroup.append(pageTitle);
  const flowSelectLabel = document.createElement("label");
  flowSelectLabel.className = "lc-builder-flow-select-label";
  flowSelectLabel.textContent = `${t("flows", locale)}: `;
  const flowSelect = document.createElement("select");
  flowSelect.className = "lc-builder-flow-select";
  flowSelect.addEventListener("change", () => {
    const id = parseInt(flowSelect.value, 10);
    if (!Number.isNaN(id) && id !== activeFlowId) {
      loadFlow(id);
    }
  });
  flowSelectLabel.append(flowSelect);
  titleGroup.append(flowSelectLabel);
  topBar.append(titleGroup);
  const actionsGroup = document.createElement("div");
  actionsGroup.className = "lc-builder-actions";
  const newFlowBtn = document.createElement("button");
  newFlowBtn.type = "button";
  newFlowBtn.className = "lc-btn-sm";
  newFlowBtn.textContent = `+ ${t("createFlow", locale)}`;
  newFlowBtn.addEventListener("click", () => void handleCreateFlow());
  actionsGroup.append(newFlowBtn);
  const dupFlowBtn = document.createElement("button");
  dupFlowBtn.type = "button";
  dupFlowBtn.className = "lc-btn-sm lc-btn-outline";
  dupFlowBtn.textContent = t("duplicateFlow", locale);
  dupFlowBtn.addEventListener("click", () => void handleDuplicateFlow());
  actionsGroup.append(dupFlowBtn);
  const importBtn = document.createElement("button");
  importBtn.type = "button";
  importBtn.className = "lc-btn-sm lc-btn-outline";
  importBtn.textContent = t("importContent", locale);
  importBtn.addEventListener("click", () => showImportModal());
  actionsGroup.append(importBtn);
  if (sessionId) {
    const saveSessionBtn = document.createElement("button");
    saveSessionBtn.type = "button";
    saveSessionBtn.className = "lc-btn-sm lc-btn-outline";
    saveSessionBtn.textContent = t("saveSessionAsFlow", locale);
    saveSessionBtn.addEventListener("click", () => void handleSaveSessionAsFlow());
    actionsGroup.append(saveSessionBtn);
  }
  const toggleAiBtn = document.createElement("button");
  toggleAiBtn.type = "button";
  toggleAiBtn.className = "lc-btn-sm lc-btn-subtle";
  toggleAiBtn.textContent = `\uD83E\uDD16 ${t("aiAssistant", locale)}`;
  toggleAiBtn.addEventListener("click", () => {
    isAiSidebarOpen = !isAiSidebarOpen;
    sidebarPane.style.display = isAiSidebarOpen ? "block" : "none";
  });
  actionsGroup.append(toggleAiBtn);
  topBar.append(actionsGroup);
  mainPane.append(topBar);
  const statusBanner = document.createElement("div");
  statusBanner.className = "lc-builder-status";
  statusBanner.style.display = "none";
  mainPane.append(statusBanner);
  function showStatus(msg, isError = false) {
    statusBanner.textContent = msg;
    statusBanner.className = `lc-builder-status ${isError ? "lc-builder-status-error" : "lc-builder-status-success"}`;
    statusBanner.style.display = "block";
    setTimeout(() => {
      if (statusBanner.textContent === msg) {
        statusBanner.style.display = "none";
      }
    }, 4000);
  }
  const flowDetailSection = document.createElement("section");
  flowDetailSection.className = "lc-builder-flow-detail";
  mainPane.append(flowDetailSection);
  const stepsSection = document.createElement("section");
  stepsSection.className = "lc-builder-steps-section";
  mainPane.append(stepsSection);
  const aiChatWidget = mountAiChat(sidebarPane, {
    locale,
    getAttachment: () => {
      if (currentFlow) {
        return {
          source_type: "flow",
          source_id: currentFlow.id,
          title: currentFlow.title
        };
      }
      return null;
    },
    onInsertDraft: (draftText) => {
      handleInsertDraft(draftText);
    }
  });
  async function loadFlows() {
    try {
      const data = await getJson("/api/v1/flows/");
      flows = data.flows ?? [];
      flowSelect.replaceChildren();
      if (flows.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = t("noStepsYet", locale);
        flowSelect.append(opt);
        renderFlowDetails();
        return;
      }
      for (const f of flows) {
        const opt = document.createElement("option");
        opt.value = String(f.id);
        opt.textContent = `${f.title} (${f.steps_count ?? 0} ${t("steps", locale).toLowerCase()})`;
        flowSelect.append(opt);
      }
      const targetId = activeFlowId && flows.some((f) => f.id === activeFlowId) ? activeFlowId : flows[0].id;
      await loadFlow(targetId);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to load flows", true);
    }
  }
  async function loadFlow(flowId) {
    try {
      activeFlowId = flowId;
      flowSelect.value = String(flowId);
      const data = await getJson(`/api/v1/flows/${flowId}/`);
      currentFlow = data;
      renderFlowDetails();
      renderSteps();
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to load flow details", true);
    }
  }
  async function handleCreateFlow() {
    const title = window.prompt(t("newFlowPrompt", locale), "New Lesson Flow");
    if (!title || !title.trim())
      return;
    try {
      const created = await postJson("/api/v1/flows/", {
        title: title.trim()
      });
      showStatus(t("flowUpdated", locale));
      await loadFlows();
      await loadFlow(created.id);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to create flow", true);
    }
  }
  async function handleDuplicateFlow() {
    if (!currentFlow)
      return;
    const title = window.prompt(t("duplicateFlowPrompt", locale), `Copy of ${currentFlow.title}`);
    if (title === null)
      return;
    try {
      const payload = {};
      if (title.trim())
        payload.title = title.trim();
      const duplicated = await postJson(`/api/v1/flows/${currentFlow.id}/duplicate/`, payload);
      showStatus(t("flowUpdated", locale));
      await loadFlows();
      await loadFlow(duplicated.id);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to duplicate flow", true);
    }
  }
  async function handleSaveSessionAsFlow() {
    if (!sessionId)
      return;
    const title = window.prompt(t("saveAsFlowPrompt", locale), "Classroom Flow");
    if (!title || !title.trim())
      return;
    try {
      const flow = await postJson(`/api/v1/sessions/${sessionId}/save-flow/`, {
        title: title.trim()
      });
      showStatus(t("flowUpdated", locale));
      await loadFlows();
      await loadFlow(flow.id);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to save session as flow", true);
    }
  }
  function renderFlowDetails() {
    flowDetailSection.replaceChildren();
    if (!currentFlow) {
      const p = document.createElement("p");
      p.className = "lc-empty-notice";
      p.textContent = t("selectFlow", locale);
      flowDetailSection.append(p);
      return;
    }
    const flowHeader = document.createElement("div");
    flowHeader.className = "lc-builder-flow-info";
    const flowTitle = document.createElement("h1");
    flowTitle.textContent = currentFlow.title;
    flowHeader.append(flowTitle);
    if (currentFlow.description) {
      const flowDesc = document.createElement("p");
      flowDesc.className = "lc-builder-flow-desc";
      flowDesc.textContent = currentFlow.description;
      flowHeader.append(flowDesc);
    }
    const metaRow = document.createElement("div");
    metaRow.className = "lc-builder-flow-meta";
    const stepsCountBadge = document.createElement("span");
    stepsCountBadge.className = "lc-badge";
    stepsCountBadge.textContent = `${currentFlow.steps.length} ${t("steps", locale)}`;
    metaRow.append(stepsCountBadge);
    flowHeader.append(metaRow);
    flowDetailSection.append(flowHeader);
  }
  function renderSteps() {
    stepsSection.replaceChildren();
    if (!currentFlow)
      return;
    const stepsHeader = document.createElement("div");
    stepsHeader.className = "lc-builder-steps-header";
    const heading = document.createElement("h3");
    heading.textContent = t("steps", locale);
    stepsHeader.append(heading);
    const addStepBtn = document.createElement("button");
    addStepBtn.type = "button";
    addStepBtn.className = "lc-btn-sm lc-btn-primary";
    addStepBtn.textContent = `+ ${t("addStep", locale)}`;
    addStepBtn.addEventListener("click", () => {
      isAddStepOpen = !isAddStepOpen;
      renderAddStepForm();
    });
    stepsHeader.append(addStepBtn);
    stepsSection.append(stepsHeader);
    const addFormContainer = document.createElement("div");
    addFormContainer.id = "lc-add-step-form-container";
    stepsSection.append(addFormContainer);
    if (isAddStepOpen)
      renderAddStepForm();
    const list = document.createElement("div");
    list.className = "lc-builder-step-list";
    if (currentFlow.steps.length === 0) {
      const emptyP = document.createElement("p");
      emptyP.className = "lc-empty-notice";
      emptyP.textContent = t("noStepsYet", locale);
      list.append(emptyP);
    } else {
      currentFlow.steps.forEach((step, index) => {
        const card = createStepCard(step, index, currentFlow.steps.length);
        list.append(card);
      });
    }
    stepsSection.append(list);
  }
  function createStepCard(step, index, total) {
    const card = document.createElement("div");
    card.className = "lc-builder-step-card";
    card.id = `step-card-${step.id}`;
    const cardHeader = document.createElement("div");
    cardHeader.className = "lc-builder-step-header";
    const titleArea = document.createElement("div");
    titleArea.className = "lc-builder-step-title-area";
    const posBadge = document.createElement("span");
    posBadge.className = "lc-step-pos";
    posBadge.textContent = `#${step.position || index + 1}`;
    titleArea.append(posBadge);
    const typeKey = step.activity_definition?.type_key || step.kind;
    const typeInfo = ACTIVITY_TYPES.find((at) => at.type_key === typeKey);
    const typeName = typeInfo ? t(typeInfo.labelKey, locale) : step.kind === "markdown" ? t("markdownContent", locale) : typeKey;
    const typeBadge = document.createElement("span");
    typeBadge.className = "lc-step-type-badge";
    typeBadge.textContent = typeName;
    titleArea.append(typeBadge);
    const stepTitle = document.createElement("strong");
    stepTitle.className = "lc-step-name";
    stepTitle.textContent = step.title || step.activity_definition?.title || typeName;
    titleArea.append(stepTitle);
    cardHeader.append(titleArea);
    const actionsArea = document.createElement("div");
    actionsArea.className = "lc-builder-step-actions";
    const upBtn = document.createElement("button");
    upBtn.type = "button";
    upBtn.className = "lc-btn-icon";
    upBtn.title = t("moveUp", locale);
    upBtn.textContent = "↑";
    upBtn.disabled = index === 0;
    upBtn.addEventListener("click", () => void handleMoveStep(index, -1));
    actionsArea.append(upBtn);
    const downBtn = document.createElement("button");
    downBtn.type = "button";
    downBtn.className = "lc-btn-icon";
    downBtn.title = t("moveDown", locale);
    downBtn.textContent = "↓";
    downBtn.disabled = index === total - 1;
    downBtn.addEventListener("click", () => void handleMoveStep(index, 1));
    actionsArea.append(downBtn);
    const isPreviewOpen = previewOpenSteps.has(step.id);
    const previewBtn = document.createElement("button");
    previewBtn.type = "button";
    previewBtn.className = `lc-btn-sm ${isPreviewOpen ? "lc-btn-primary" : "lc-btn-outline"}`;
    previewBtn.textContent = isPreviewOpen ? t("hidePreview", locale) : t("showPreview", locale);
    previewBtn.addEventListener("click", () => {
      if (previewOpenSteps.has(step.id)) {
        previewOpenSteps.delete(step.id);
      } else {
        previewOpenSteps.add(step.id);
      }
      renderSteps();
    });
    actionsArea.append(previewBtn);
    if (sessionId) {
      const launchBtn = document.createElement("button");
      launchBtn.type = "button";
      launchBtn.className = "lc-btn-sm lc-btn-secondary";
      launchBtn.textContent = `\uD83D\uDE80 ${t("launchToClassroom", locale)}`;
      launchBtn.addEventListener("click", () => void handleLaunchStep(step));
      actionsArea.append(launchBtn);
    }
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "lc-btn-sm lc-btn-danger";
    delBtn.textContent = t("removeStep", locale);
    delBtn.addEventListener("click", () => void handleDeleteStep(step));
    actionsArea.append(delBtn);
    cardHeader.append(actionsArea);
    card.append(cardHeader);
    if (isPreviewOpen) {
      const previewBox = document.createElement("div");
      previewBox.className = "lc-builder-step-preview";
      renderStepLivePreview(previewBox, step);
      card.append(previewBox);
    }
    return card;
  }
  function renderStepLivePreview(container2, step) {
    container2.replaceChildren();
    const previewHeader = document.createElement("div");
    previewHeader.className = "lc-preview-header";
    const headerTitle = document.createElement("small");
    headerTitle.textContent = `\uD83D\uDC41 ${t("previewHeading", locale)}`;
    previewHeader.append(headerTitle);
    container2.append(previewHeader);
    const definition = step.activity_definition?.definition ?? step.content ?? {};
    const promptText = definition.prompt || step.title || "";
    const typeKey = step.activity_definition?.type_key || step.kind;
    if (promptText) {
      const promptEl = document.createElement("h4");
      promptEl.className = "lc-preview-prompt";
      promptEl.textContent = promptText;
      container2.append(promptEl);
    }
    if (typeKey === "liveclassroom.single_choice" || typeKey === "liveclassroom.multiple_choice" || typeKey === "liveclassroom.poll" || typeKey === "liveclassroom.ranking") {
      const options = Array.isArray(definition.options) ? definition.options : [];
      const isMultiple = typeKey === "liveclassroom.multiple_choice";
      const isRanking = typeKey === "liveclassroom.ranking";
      const list = document.createElement("div");
      list.className = "lc-preview-options-list";
      options.forEach((opt, idx) => {
        const item = document.createElement("div");
        item.className = "lc-preview-option-item";
        if (isRanking) {
          item.textContent = `${idx + 1}. ${opt.text || opt.id}`;
        } else {
          const input = document.createElement("input");
          input.type = isMultiple ? "checkbox" : "radio";
          input.name = `preview-opt-${step.id}`;
          input.disabled = true;
          const label = document.createElement("span");
          label.textContent = ` ${opt.id ? opt.id + ". " : ""}${opt.text || ""}`;
          item.append(input, label);
        }
        list.append(item);
      });
      container2.append(list);
      if (definition.answer) {
        const ans = document.createElement("p");
        ans.className = "lc-preview-answer";
        ans.textContent = `${t("correctAnswer", locale)}: ${Array.isArray(definition.answer) ? definition.answer.join(", ") : String(definition.answer)}`;
        container2.append(ans);
      }
      if (definition.explanation_markdown || definition.explanation) {
        const exp = document.createElement("p");
        exp.className = "lc-preview-explanation";
        exp.textContent = `${t("explanation", locale)}: ${String(definition.explanation_markdown || definition.explanation)}`;
        container2.append(exp);
      }
    } else if (typeKey === "liveclassroom.true_false") {
      const btnRow = document.createElement("div");
      btnRow.className = "lc-preview-tf-row";
      const tBtn = document.createElement("button");
      tBtn.type = "button";
      tBtn.disabled = true;
      tBtn.textContent = "True";
      const fBtn = document.createElement("button");
      fBtn.type = "button";
      fBtn.disabled = true;
      fBtn.textContent = "False";
      btnRow.append(tBtn, fBtn);
      container2.append(btnRow);
      if (definition.answer) {
        const ans = document.createElement("p");
        ans.className = "lc-preview-answer";
        ans.textContent = `${t("correctAnswer", locale)}: ${Array.isArray(definition.answer) ? definition.answer.join(", ") : String(definition.answer)}`;
        container2.append(ans);
      }
    } else if (typeKey === "liveclassroom.short_text" || typeKey === "liveclassroom.word_cloud") {
      const input = document.createElement("input");
      input.type = "text";
      input.className = "lc-preview-input";
      input.placeholder = typeKey === "liveclassroom.word_cloud" ? "Enter a word…" : "Enter your answer…";
      input.disabled = true;
      container2.append(input);
    } else if (typeKey === "liveclassroom.numeric") {
      const input = document.createElement("input");
      input.type = "number";
      input.className = "lc-preview-input";
      input.disabled = true;
      if (definition.minimum !== undefined)
        input.min = String(definition.minimum);
      if (definition.maximum !== undefined)
        input.max = String(definition.maximum);
      if (definition.step !== undefined)
        input.step = String(definition.step);
      container2.append(input);
    } else if (typeKey === "liveclassroom.rating") {
      const starsRow = document.createElement("div");
      starsRow.className = "lc-preview-rating-row";
      const max = typeof definition.maximum === "number" ? definition.maximum : 5;
      for (let i = 1;i <= max; i++) {
        const star = document.createElement("button");
        star.type = "button";
        star.className = "lc-rating-btn";
        star.disabled = true;
        star.textContent = String(i);
        starsRow.append(star);
      }
      container2.append(starsRow);
    } else if (typeKey === "liveclassroom.timer") {
      const timerBox = document.createElement("div");
      timerBox.className = "lc-preview-timer-box";
      const duration = definition.duration_seconds ?? 60;
      const label = definition.label || t("timer", locale);
      timerBox.textContent = `⏱ ${label}: ${duration}${t("seconds", locale)}`;
      container2.append(timerBox);
    } else if (typeKey === "liveclassroom.markdown" || step.kind === "markdown") {
      const mdContent = definition.markdown || "";
      const mdBox = document.createElement("div");
      mdBox.className = "lc-preview-markdown";
      mdBox.textContent = mdContent;
      container2.append(mdBox);
    } else if (typeKey === "liveclassroom.media") {
      const url = definition.url || "";
      const mediaType = definition.media_type || "image";
      const mediaBox = document.createElement("div");
      mediaBox.className = "lc-preview-media";
      if (mediaType === "image") {
        const img = document.createElement("img");
        img.src = url;
        img.alt = definition.caption || "Preview image";
        img.style.maxWidth = "100%";
        img.style.maxHeight = "16rem";
        mediaBox.append(img);
      } else {
        const link = document.createElement("a");
        link.href = url;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = `\uD83D\uDD17 Open ${mediaType}: ${url}`;
        mediaBox.append(link);
      }
      if (definition.caption) {
        const cap = document.createElement("p");
        cap.className = "lc-preview-caption";
        cap.textContent = String(definition.caption);
        mediaBox.append(cap);
      }
      container2.append(mediaBox);
    }
  }
  async function handleMoveStep(index, direction) {
    if (!currentFlow)
      return;
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= currentFlow.steps.length)
      return;
    const newSteps = [...currentFlow.steps];
    const [moved] = newSteps.splice(index, 1);
    newSteps.splice(targetIndex, 0, moved);
    const stepIds = newSteps.map((s) => s.id);
    try {
      const res = await putJson(`/api/v1/flows/${currentFlow.id}/steps/reorder/`, { step_ids: stepIds });
      currentFlow.steps = res.steps;
      renderSteps();
      showStatus(t("stepsReordered", locale));
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to reorder steps", true);
    }
  }
  async function handleDeleteStep(step) {
    if (!currentFlow)
      return;
    if (!window.confirm(t("confirmDeleteStep", locale)))
      return;
    try {
      await deleteJson(`/api/v1/flows/${currentFlow.id}/steps/${step.id}/`);
      currentFlow.steps = currentFlow.steps.filter((s) => s.id !== step.id);
      previewOpenSteps.delete(step.id);
      renderSteps();
      showStatus(t("stepDeleted", locale));
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to delete step", true);
    }
  }
  async function handleLaunchStep(step) {
    if (!sessionId)
      return;
    try {
      await postJson(`/api/v1/sessions/${sessionId}/activities/`, {
        flow_step_id: step.id
      });
      showStatus(t("launchedSuccess", locale));
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to launch activity", true);
    }
  }
  function renderAddStepForm(initialDraft) {
    const containerEl = document.getElementById("lc-add-step-form-container");
    if (!containerEl)
      return;
    containerEl.replaceChildren();
    if (!isAddStepOpen)
      return;
    const formWrapper = document.createElement("div");
    formWrapper.className = "lc-builder-step-form";
    const formHeading = document.createElement("h4");
    formHeading.textContent = t("addStep", locale);
    formWrapper.append(formHeading);
    const errorBanner = document.createElement("div");
    errorBanner.className = "lc-form-error";
    errorBanner.style.display = "none";
    formWrapper.append(errorBanner);
    const titleGroup2 = document.createElement("div");
    titleGroup2.className = "lc-form-group";
    const titleLabel = document.createElement("label");
    titleLabel.textContent = `${t("flowTitle", locale)}: `;
    const titleInput = document.createElement("input");
    titleInput.type = "text";
    titleInput.className = "lc-input";
    titleInput.placeholder = "e.g. Mendel's First Experiment";
    titleGroup2.append(titleLabel, titleInput);
    formWrapper.append(titleGroup2);
    const typeGroup = document.createElement("div");
    typeGroup.className = "lc-form-group";
    const typeLabel = document.createElement("label");
    typeLabel.textContent = `${t("stepType", locale)}: `;
    const typeSelect = document.createElement("select");
    typeSelect.className = "lc-select";
    for (const at of ACTIVITY_TYPES) {
      const opt = document.createElement("option");
      opt.value = at.type_key;
      opt.textContent = t(at.labelKey, locale);
      typeSelect.append(opt);
    }
    typeGroup.append(typeLabel, typeSelect);
    formWrapper.append(typeGroup);
    const dynamicFields = document.createElement("div");
    dynamicFields.className = "lc-dynamic-fields";
    formWrapper.append(dynamicFields);
    function renderDynamicInputs() {
      dynamicFields.replaceChildren();
      const selectedType = typeSelect.value;
      if (selectedType === "liveclassroom.single_choice" || selectedType === "liveclassroom.multiple_choice" || selectedType === "liveclassroom.poll" || selectedType === "liveclassroom.ranking") {
        const pGroup = document.createElement("div");
        pGroup.className = "lc-form-group";
        const pLabel = document.createElement("label");
        pLabel.textContent = `${t("promptLabel", locale)}: `;
        const pInput = document.createElement("textarea");
        pInput.className = "lc-textarea";
        pInput.id = "lc-field-prompt";
        pInput.rows = 2;
        if (initialDraft)
          pInput.value = initialDraft;
        pGroup.append(pLabel, pInput);
        dynamicFields.append(pGroup);
        const optGroup = document.createElement("div");
        optGroup.className = "lc-form-group";
        const optLabel = document.createElement("label");
        optLabel.textContent = `${t("optionsLabel", locale)}: `;
        const optInput = document.createElement("textarea");
        optInput.className = "lc-textarea";
        optInput.id = "lc-field-options";
        optInput.rows = 4;
        optInput.placeholder = `Choice 1
Choice 2
Choice 3
Choice 4`;
        optGroup.append(optLabel, optInput);
        dynamicFields.append(optGroup);
        if (selectedType === "liveclassroom.single_choice" || selectedType === "liveclassroom.multiple_choice") {
          const ansGroup = document.createElement("div");
          ansGroup.className = "lc-form-group";
          const ansLabel = document.createElement("label");
          ansLabel.textContent = `${t("correctAnswer", locale)} (e.g. A or A, B): `;
          const ansInput = document.createElement("input");
          ansInput.type = "text";
          ansInput.className = "lc-input";
          ansInput.id = "lc-field-answer";
          ansGroup.append(ansLabel, ansInput);
          dynamicFields.append(ansGroup);
        }
        const expGroup = document.createElement("div");
        expGroup.className = "lc-form-group";
        const expLabel = document.createElement("label");
        expLabel.textContent = `${t("explanation", locale)}: `;
        const expInput = document.createElement("textarea");
        expInput.className = "lc-textarea";
        expInput.id = "lc-field-explanation";
        expInput.rows = 2;
        expGroup.append(expLabel, expInput);
        dynamicFields.append(expGroup);
      } else if (selectedType === "liveclassroom.true_false") {
        const pGroup = document.createElement("div");
        pGroup.className = "lc-form-group";
        const pLabel = document.createElement("label");
        pLabel.textContent = `${t("promptLabel", locale)}: `;
        const pInput = document.createElement("textarea");
        pInput.className = "lc-textarea";
        pInput.id = "lc-field-prompt";
        pInput.rows = 2;
        if (initialDraft)
          pInput.value = initialDraft;
        pGroup.append(pLabel, pInput);
        dynamicFields.append(pGroup);
        const ansGroup = document.createElement("div");
        ansGroup.className = "lc-form-group";
        const ansLabel = document.createElement("label");
        ansLabel.textContent = `${t("correctAnswer", locale)}: `;
        const ansSelect = document.createElement("select");
        ansSelect.className = "lc-select";
        ansSelect.id = "lc-field-answer";
        const optT = document.createElement("option");
        optT.value = "true";
        optT.textContent = "True";
        const optF = document.createElement("option");
        optF.value = "false";
        optF.textContent = "False";
        ansSelect.append(optT, optF);
        ansGroup.append(ansLabel, ansSelect);
        dynamicFields.append(ansGroup);
      } else if (selectedType === "liveclassroom.short_text" || selectedType === "liveclassroom.word_cloud") {
        const pGroup = document.createElement("div");
        pGroup.className = "lc-form-group";
        const pLabel = document.createElement("label");
        pLabel.textContent = `${t("promptLabel", locale)}: `;
        const pInput = document.createElement("textarea");
        pInput.className = "lc-textarea";
        pInput.id = "lc-field-prompt";
        pInput.rows = 2;
        if (initialDraft)
          pInput.value = initialDraft;
        pGroup.append(pLabel, pInput);
        dynamicFields.append(pGroup);
        if (selectedType === "liveclassroom.word_cloud") {
          const swGroup = document.createElement("div");
          swGroup.className = "lc-form-group";
          const swLabel = document.createElement("label");
          swLabel.textContent = `${t("stopWordsLabel", locale)}: `;
          const swInput = document.createElement("input");
          swInput.type = "text";
          swInput.className = "lc-input";
          swInput.id = "lc-field-stopwords";
          swInput.placeholder = "e.g. the, a, is";
          swGroup.append(swLabel, swInput);
          dynamicFields.append(swGroup);
        }
      } else if (selectedType === "liveclassroom.numeric" || selectedType === "liveclassroom.rating") {
        const pGroup = document.createElement("div");
        pGroup.className = "lc-form-group";
        const pLabel = document.createElement("label");
        pLabel.textContent = `${t("promptLabel", locale)}: `;
        const pInput = document.createElement("textarea");
        pInput.className = "lc-textarea";
        pInput.id = "lc-field-prompt";
        pInput.rows = 2;
        if (initialDraft)
          pInput.value = initialDraft;
        pGroup.append(pLabel, pInput);
        dynamicFields.append(pGroup);
        const row = document.createElement("div");
        row.className = "lc-form-row";
        const minGroup = document.createElement("div");
        minGroup.className = "lc-form-group";
        const minLabel = document.createElement("label");
        minLabel.textContent = `${t("numericMinLabel", locale)}: `;
        const minInput = document.createElement("input");
        minInput.type = "number";
        minInput.className = "lc-input";
        minInput.id = "lc-field-min";
        if (selectedType === "liveclassroom.rating")
          minInput.value = "1";
        minGroup.append(minLabel, minInput);
        row.append(minGroup);
        const maxGroup = document.createElement("div");
        maxGroup.className = "lc-form-group";
        const maxLabel = document.createElement("label");
        maxLabel.textContent = `${t("numericMaxLabel", locale)}: `;
        const maxInput = document.createElement("input");
        maxInput.type = "number";
        maxInput.className = "lc-input";
        maxInput.id = "lc-field-max";
        if (selectedType === "liveclassroom.rating")
          maxInput.value = "5";
        maxGroup.append(maxLabel, maxInput);
        row.append(maxGroup);
        dynamicFields.append(row);
      } else if (selectedType === "liveclassroom.timer") {
        const durGroup = document.createElement("div");
        durGroup.className = "lc-form-group";
        const durLabel = document.createElement("label");
        durLabel.textContent = `${t("durationSecondsLabel", locale)}: `;
        const durInput = document.createElement("input");
        durInput.type = "number";
        durInput.className = "lc-input";
        durInput.id = "lc-field-duration";
        durInput.value = "60";
        durGroup.append(durLabel, durInput);
        dynamicFields.append(durGroup);
      } else if (selectedType === "liveclassroom.markdown") {
        const mdGroup = document.createElement("div");
        mdGroup.className = "lc-form-group";
        const mdLabel = document.createElement("label");
        mdLabel.textContent = `${t("markdownContentLabel", locale)}: `;
        const mdInput = document.createElement("textarea");
        mdInput.className = "lc-textarea";
        mdInput.id = "lc-field-markdown";
        mdInput.rows = 6;
        if (initialDraft)
          mdInput.value = initialDraft;
        mdGroup.append(mdLabel, mdInput);
        dynamicFields.append(mdGroup);
      } else if (selectedType === "liveclassroom.media") {
        const urlGroup = document.createElement("div");
        urlGroup.className = "lc-form-group";
        const urlLabel = document.createElement("label");
        urlLabel.textContent = `${t("mediaUrlLabel", locale)}: `;
        const urlInput = document.createElement("input");
        urlInput.type = "url";
        urlInput.className = "lc-input";
        urlInput.id = "lc-field-url";
        urlGroup.append(urlLabel, urlInput);
        dynamicFields.append(urlGroup);
        const typeG = document.createElement("div");
        typeG.className = "lc-form-group";
        const tLab = document.createElement("label");
        tLab.textContent = `${t("mediaTypeLabel", locale)}: `;
        const tSel = document.createElement("select");
        tSel.className = "lc-select";
        tSel.id = "lc-field-media-type";
        for (const mt of ["image", "video", "audio"]) {
          const opt = document.createElement("option");
          opt.value = mt;
          opt.textContent = mt;
          tSel.append(opt);
        }
        typeG.append(tLab, tSel);
        dynamicFields.append(typeG);
        const capGroup = document.createElement("div");
        capGroup.className = "lc-form-group";
        const capLabel = document.createElement("label");
        capLabel.textContent = `${t("captionLabel", locale)}: `;
        const capInput = document.createElement("input");
        capInput.type = "text";
        capInput.className = "lc-input";
        capInput.id = "lc-field-caption";
        capGroup.append(capLabel, capInput);
        dynamicFields.append(capGroup);
      }
    }
    typeSelect.addEventListener("change", renderDynamicInputs);
    renderDynamicInputs();
    const btnRow = document.createElement("div");
    btnRow.className = "lc-form-btn-row";
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "lc-btn-sm lc-btn-primary";
    saveBtn.textContent = t("saveStep", locale);
    saveBtn.addEventListener("click", () => void handleSaveStep(errorBanner, titleInput, typeSelect));
    btnRow.append(saveBtn);
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "lc-btn-sm lc-btn-outline";
    cancelBtn.textContent = t("cancelStep", locale);
    cancelBtn.addEventListener("click", () => {
      isAddStepOpen = false;
      containerEl.replaceChildren();
    });
    btnRow.append(cancelBtn);
    formWrapper.append(btnRow);
    containerEl.append(formWrapper);
  }
  async function handleSaveStep(errorBanner, titleInput, typeSelect) {
    if (!currentFlow)
      return;
    errorBanner.style.display = "none";
    errorBanner.textContent = "";
    const selectedType = typeSelect.value;
    const titleVal = titleInput.value.trim();
    const promptEl = document.getElementById("lc-field-prompt");
    const promptVal = promptEl?.value.trim() ?? "";
    if (selectedType === "liveclassroom.single_choice" || selectedType === "liveclassroom.multiple_choice" || selectedType === "liveclassroom.poll" || selectedType === "liveclassroom.ranking") {
      if (!promptVal && !titleVal) {
        errorBanner.textContent = t("validationError", locale);
        errorBanner.style.display = "block";
        return;
      }
      const optEl = document.getElementById("lc-field-options");
      const lines = (optEl?.value || "").split(`
`).map((l) => l.trim()).filter(Boolean);
      if (lines.length < 2) {
        errorBanner.textContent = "Please provide at least two options.";
        errorBanner.style.display = "block";
        return;
      }
      const options = lines.map((text, idx) => {
        const id = String.fromCharCode(65 + idx);
        const cleaned = text.replace(/^[A-Z][.:]\s*/, "");
        return { id, text: cleaned || text };
      });
      const definition = {
        prompt: promptVal || titleVal,
        options
      };
      const ansEl = document.getElementById("lc-field-answer");
      if (ansEl && ansEl.value.trim()) {
        const rawAns = ansEl.value.split(/[, ]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
        definition.answer = selectedType === "liveclassroom.single_choice" ? [rawAns[0]] : rawAns;
      }
      const expEl = document.getElementById("lc-field-explanation");
      if (expEl && expEl.value.trim()) {
        definition.explanation_markdown = expEl.value.trim();
      }
      await submitStepPayload({
        kind: "activity",
        title: titleVal || promptVal,
        activity_definition: {
          title: titleVal || promptVal,
          type_key: selectedType,
          definition
        }
      });
    } else if (selectedType === "liveclassroom.true_false") {
      if (!promptVal && !titleVal) {
        errorBanner.textContent = t("validationError", locale);
        errorBanner.style.display = "block";
        return;
      }
      const ansSel = document.getElementById("lc-field-answer");
      const ansVal = ansSel?.value || "true";
      await submitStepPayload({
        kind: "activity",
        title: titleVal || promptVal,
        activity_definition: {
          title: titleVal || promptVal,
          type_key: selectedType,
          definition: {
            prompt: promptVal || titleVal,
            options: [
              { id: "true", text: "True" },
              { id: "false", text: "False" }
            ],
            answer: [ansVal]
          }
        }
      });
    } else if (selectedType === "liveclassroom.short_text" || selectedType === "liveclassroom.word_cloud") {
      if (!promptVal && !titleVal) {
        errorBanner.textContent = t("validationError", locale);
        errorBanner.style.display = "block";
        return;
      }
      const definition = { prompt: promptVal || titleVal };
      if (selectedType === "liveclassroom.word_cloud") {
        const swEl = document.getElementById("lc-field-stopwords");
        if (swEl && swEl.value.trim()) {
          definition.stop_words = swEl.value.split(/[, ]+/).map((s) => s.trim()).filter(Boolean);
        }
      }
      await submitStepPayload({
        kind: "activity",
        title: titleVal || promptVal,
        activity_definition: {
          title: titleVal || promptVal,
          type_key: selectedType,
          definition
        }
      });
    } else if (selectedType === "liveclassroom.numeric" || selectedType === "liveclassroom.rating") {
      if (!promptVal && !titleVal) {
        errorBanner.textContent = t("validationError", locale);
        errorBanner.style.display = "block";
        return;
      }
      const definition = { prompt: promptVal || titleVal };
      const minEl = document.getElementById("lc-field-min");
      const maxEl = document.getElementById("lc-field-max");
      if (minEl && minEl.value)
        definition.minimum = parseFloat(minEl.value);
      if (maxEl && maxEl.value)
        definition.maximum = parseFloat(maxEl.value);
      await submitStepPayload({
        kind: "activity",
        title: titleVal || promptVal,
        activity_definition: {
          title: titleVal || promptVal,
          type_key: selectedType,
          definition
        }
      });
    } else if (selectedType === "liveclassroom.timer") {
      const durEl = document.getElementById("lc-field-duration");
      const durVal = parseFloat(durEl?.value || "0");
      if (!durVal || durVal <= 0) {
        errorBanner.textContent = "Duration must be greater than zero.";
        errorBanner.style.display = "block";
        return;
      }
      await submitStepPayload({
        kind: "activity",
        title: titleVal || `Timer ${durVal}s`,
        activity_definition: {
          title: titleVal || `Timer ${durVal}s`,
          type_key: selectedType,
          definition: {
            duration_seconds: durVal,
            label: titleVal || "Timer"
          }
        }
      });
    } else if (selectedType === "liveclassroom.markdown") {
      const mdEl = document.getElementById("lc-field-markdown");
      const mdVal = mdEl?.value.trim() ?? "";
      if (!mdVal) {
        errorBanner.textContent = "Markdown content is required.";
        errorBanner.style.display = "block";
        return;
      }
      await submitStepPayload({
        kind: "markdown",
        title: titleVal || "Lecture Note",
        content: { markdown: mdVal }
      });
    } else if (selectedType === "liveclassroom.media") {
      const urlEl = document.getElementById("lc-field-url");
      const urlVal = urlEl?.value.trim() ?? "";
      if (!urlVal) {
        errorBanner.textContent = "Media URL is required.";
        errorBanner.style.display = "block";
        return;
      }
      const mtEl = document.getElementById("lc-field-media-type");
      const capEl = document.getElementById("lc-field-caption");
      await submitStepPayload({
        kind: "activity",
        title: titleVal || "Media Presentation",
        activity_definition: {
          title: titleVal || "Media Presentation",
          type_key: selectedType,
          definition: {
            url: urlVal,
            media_type: mtEl?.value || "image",
            caption: capEl?.value.trim() || ""
          }
        }
      });
    }
  }
  async function submitStepPayload(payload) {
    if (!currentFlow)
      return;
    try {
      await postJson(`/api/v1/flows/${currentFlow.id}/steps/`, payload);
      isAddStepOpen = false;
      showStatus(t("stepAdded", locale));
      await loadFlow(currentFlow.id);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to add step", true);
    }
  }
  function handleInsertDraft(draftText) {
    isAddStepOpen = true;
    renderAddStepForm(draftText);
    const formEl = document.getElementById("lc-add-step-form-container");
    if (formEl)
      formEl.scrollIntoView({ behavior: "smooth" });
    showStatus("AI draft inserted into step editor. Review and save.");
  }
  function showImportModal() {
    const existingModal = document.getElementById("lc-import-modal");
    if (existingModal)
      existingModal.remove();
    const overlay = document.createElement("div");
    overlay.id = "lc-import-modal";
    overlay.className = "lc-modal-overlay";
    const modal = document.createElement("div");
    modal.className = "lc-modal";
    const mTitle = document.createElement("h3");
    mTitle.textContent = t("importContent", locale);
    modal.append(mTitle);
    const mError = document.createElement("div");
    mError.className = "lc-form-error";
    mError.style.display = "none";
    modal.append(mError);
    const fmtGroup = document.createElement("div");
    fmtGroup.className = "lc-form-group";
    const fmtLabel = document.createElement("label");
    fmtLabel.textContent = `${t("formatLabel", locale)}: `;
    const fmtSelect = document.createElement("select");
    fmtSelect.className = "lc-select";
    const optAuto = document.createElement("option");
    optAuto.value = "";
    optAuto.textContent = t("autoDetect", locale);
    const optJson = document.createElement("option");
    optJson.value = "json";
    optJson.textContent = "JSON";
    const optMd = document.createElement("option");
    optMd.value = "markdown";
    optMd.textContent = "Markdown / YAML";
    fmtSelect.append(optAuto, optJson, optMd);
    fmtGroup.append(fmtLabel, fmtSelect);
    modal.append(fmtGroup);
    const textGroup = document.createElement("div");
    textGroup.className = "lc-form-group";
    const textInput = document.createElement("textarea");
    textInput.className = "lc-textarea";
    textInput.rows = 8;
    textInput.placeholder = t("importPlaceholder", locale);
    textGroup.append(textInput);
    modal.append(textGroup);
    const btnRow = document.createElement("div");
    btnRow.className = "lc-modal-actions";
    const doImportBtn = document.createElement("button");
    doImportBtn.type = "button";
    doImportBtn.className = "lc-btn-sm lc-btn-primary";
    doImportBtn.textContent = t("importButton", locale);
    doImportBtn.addEventListener("click", async () => {
      const source = textInput.value.trim();
      if (!source) {
        mError.textContent = "Please paste content to import.";
        mError.style.display = "block";
        return;
      }
      try {
        doImportBtn.disabled = true;
        const body = { source };
        if (fmtSelect.value)
          body.format = fmtSelect.value;
        const imported = await postJson("/api/v1/flows/import/", body);
        overlay.remove();
        showStatus(t("importSuccess", locale));
        await loadFlows();
        await loadFlow(imported.id);
      } catch (err) {
        doImportBtn.disabled = false;
        mError.textContent = `${t("importError", locale)} ${err instanceof Error ? err.message : String(err)}`;
        mError.style.display = "block";
      }
    });
    btnRow.append(doImportBtn);
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "lc-btn-sm lc-btn-outline";
    cancelBtn.textContent = t("cancel", locale);
    cancelBtn.addEventListener("click", () => overlay.remove());
    btnRow.append(cancelBtn);
    modal.append(btnRow);
    overlay.append(modal);
    document.body.append(overlay);
  }
  loadFlows();
}

// src/app.ts
function getLabels(locale) {
  const loc = locale ?? getLocale();
  return {
    activity: t("activity", loc),
    waiting: t("waiting", loc),
    unavailable: t("unavailable", loc),
    submit: t("submit", loc),
    update: t("update", loc),
    saved: t("saved", loc),
    stale: t("stale", loc),
    noAnswer: t("noAnswer", loc),
    state: t("state", loc),
    revision: t("revision", loc),
    close: t("close", loc),
    reveal: t("reveal", loc),
    start: t("start", loc),
    pause: t("pause", loc),
    end: t("end", loc),
    display: t("display", loc),
    participants: t("participants", loc),
    publish: t("publish", loc),
    showPrompt: t("showPrompt", loc),
    showAggregate: t("showAggregate", loc),
    showAnswer: t("showAnswer", loc),
    showExplanation: t("showExplanation", loc),
    showOwnStatus: t("showOwnStatus", loc),
    allowReview: t("allowReview", loc),
    admit: t("admit", loc),
    pending: t("pending", loc),
    chat: t("chat", loc),
    chatDisabled: t("chatDisabled", loc),
    chatUnavailable: t("chatUnavailable", loc),
    send: t("send", loc),
    enableChat: t("enableChat", loc),
    displayPreview: t("displayPreview", loc),
    participantPreview: t("participantPreview", loc),
    history: t("history", loc),
    timer: t("timer", loc),
    timerRemaining: t("timerRemaining", loc),
    timerFinished: t("timerFinished", loc),
    seconds: t("seconds", loc),
    confirmEnd: t("confirmEnd", loc),
    noActivityPublished: t("noActivityPublished", loc),
    controls: t("controls", loc),
    audienceVisibility: t("audienceVisibility", loc),
    enterDisplayName: t("enterDisplayName", loc),
    joinClassroom: t("joinClassroom", loc),
    displayName: t("displayName", loc),
    signInRequired: t("signInRequired", loc),
    waitingAdmission: t("waitingAdmission", loc),
    notShownYet: t("notShownYet", loc),
    noHistory: t("noHistory", loc),
    historyUnavailable: t("historyUnavailable", loc),
    noMessages: t("noMessages", loc),
    updated: t("updated", loc),
    results: t("results", loc),
    noResponses: t("noResponses", loc),
    publishToReview: t("publishToReview", loc),
    analyticsUnavailable: t("analyticsUnavailable", loc),
    wordCloud: t("wordCloud", loc),
    wordFrequencies: t("wordFrequencies", loc),
    moderation: t("moderation", loc),
    responseRate: t("responseRate", loc),
    admitted: t("admitted", loc),
    connected: t("connected", loc),
    attended: t("attended", loc)
  };
}
var labels = new Proxy({}, {
  get(_target, prop) {
    return t(prop);
  }
});
function text(tag, value) {
  const node = document.createElement(tag);
  node.textContent = String(value ?? "");
  return node;
}
function record(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}
function stringValue(value, fallback = "") {
  return typeof value === "string" ? value : fallback;
}
function numberValue(value) {
  if (typeof value === "number")
    return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !value.trim())
    return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function renderMarkdownText(markdown) {
  const container = document.createElement("div");
  container.className = "lc-markdown-body";
  const lines = markdown.split(`
`);
  let inCodeBlock = false;
  let codeBuffer = [];
  let currentList = null;
  let inListType = null;
  let currentBlockquote = null;
  const flushList = () => {
    if (currentList) {
      container.append(currentList);
      currentList = null;
      inListType = null;
    }
  };
  const flushBlockquote = () => {
    if (currentBlockquote) {
      container.append(currentBlockquote);
      currentBlockquote = null;
    }
  };
  const formatInline = (escaped) => {
    return escaped.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_]+)__/g, "<strong>$1</strong>").replace(/\*([^*]+)\*/g, "<em>$1</em>").replace(/_([^_]+)_/g, "<em>$1</em>").replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  };
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith("```")) {
      flushList();
      flushBlockquote();
      if (inCodeBlock) {
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = codeBuffer.join(`
`);
        pre.append(code);
        container.append(pre);
        codeBuffer = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
        codeBuffer = [];
      }
      continue;
    }
    if (inCodeBlock) {
      codeBuffer.push(line);
      continue;
    }
    if (!trimmed) {
      flushList();
      flushBlockquote();
      continue;
    }
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushList();
      flushBlockquote();
      const level = Math.min(headingMatch[1].length, 6);
      const h = document.createElement(`h${level}`);
      h.innerHTML = formatInline(escapeHtml(headingMatch[2]));
      container.append(h);
      continue;
    }
    if (trimmed.startsWith(">")) {
      flushList();
      const quoteText = trimmed.replace(/^>\s*/, "");
      if (!currentBlockquote) {
        currentBlockquote = document.createElement("blockquote");
      }
      const p2 = document.createElement("p");
      p2.innerHTML = formatInline(escapeHtml(quoteText));
      currentBlockquote.append(p2);
      continue;
    } else {
      flushBlockquote();
    }
    const ulMatch = trimmed.match(/^[-*+]\s+(.*)$/);
    if (ulMatch) {
      if (inListType !== "ul") {
        flushList();
        currentList = document.createElement("ul");
        inListType = "ul";
      }
      const li = document.createElement("li");
      li.innerHTML = formatInline(escapeHtml(ulMatch[1]));
      currentList?.append(li);
      continue;
    }
    const olMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (olMatch) {
      if (inListType !== "ol") {
        flushList();
        currentList = document.createElement("ol");
        inListType = "ol";
      }
      const li = document.createElement("li");
      li.innerHTML = formatInline(escapeHtml(olMatch[1]));
      currentList?.append(li);
      continue;
    }
    flushList();
    const p = document.createElement("p");
    p.innerHTML = formatInline(escapeHtml(trimmed));
    container.append(p);
  }
  flushList();
  flushBlockquote();
  if (inCodeBlock && codeBuffer.length) {
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = codeBuffer.join(`
`);
    pre.append(code);
    container.append(pre);
  }
  return container;
}
function activityKind(activity) {
  const definition = activity.definition;
  const typeKey = stringValue(definition.type_key);
  if (typeKey)
    return typeKey.split(".").pop() ?? typeKey;
  const question = record(definition.question);
  return stringValue(definition.kind, stringValue(question.type, stringValue(question.question_type)));
}
function activityContent(activity) {
  const definition = activity.definition;
  const content = record(definition.content);
  const question = record(definition.question);
  if (Object.keys(content).length)
    return content;
  return question;
}
function questionPrompt(activity) {
  const definition = activity.definition;
  const content = activityContent(activity);
  return stringValue(content.prompt, stringValue(content.stem_markdown, stringValue(definition.prompt, stringValue(definition.stem_markdown))));
}
function choicesFor(activity) {
  const content = activityContent(activity);
  const data = record(content.data);
  const raw = Array.isArray(content.options) ? content.options : Array.isArray(content.choices) ? content.choices : Array.isArray(data.options) ? data.options : Array.isArray(data.choices) ? data.choices : [];
  return raw.flatMap((item, index) => {
    if (typeof item === "string")
      return [{ id: String.fromCharCode(65 + index), text: item }];
    const option = record(item);
    const id = stringValue(option.id);
    const optionText = stringValue(option.text, stringValue(option.label));
    return id && optionText ? [{ id, text: optionText }] : [];
  });
}
function answerText(answer, key) {
  const value = answer[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}
function selectedChoices(answer) {
  const selected = answer.ranking ?? answer.choices ?? answer.choice;
  return Array.isArray(selected) ? selected.map(String) : selected === undefined ? [] : [String(selected)];
}
function submitUrl(stateUrl, activity) {
  return apiEndpoint(stateUrl, `activities/${activity.id}/submissions`);
}
function appendPrompt(parent, activity) {
  const prompt = questionPrompt(activity);
  if (prompt)
    parent.append(text("p", prompt));
  const content = activityContent(activity);
  const markdown = stringValue(content.markdown, stringValue(activity.definition.markdown));
  if (markdown && markdown !== prompt) {
    parent.append(renderMarkdownText(markdown));
  }
}
function displayAnswer(value) {
  if (Array.isArray(value))
    return value.map(String).join(", ");
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean")
    return String(value);
  return "";
}
function appendChoicePresentation(parent, activity) {
  const choices = choicesFor(activity);
  if (!choices.length)
    return;
  const list = document.createElement("ul");
  for (const option of choices)
    list.append(text("li", `${option.id}. ${option.text}`));
  parent.append(list);
}
function appendRevealedFeedback(parent, activity, locale = getLocale()) {
  const content = activityContent(activity);
  const answer = displayAnswer(content.answer ?? content.correct_answer ?? activity.definition.answer);
  if (answer) {
    const label = locale === "zh-Hans" ? "正确答案" : "Answer";
    parent.append(text("p", `${label}: ${answer}`));
  }
  const explanation = stringValue(content.explanation_markdown, stringValue(content.explanation));
  if (explanation) {
    parent.append(renderMarkdownText(explanation));
  }
}
function answerFor(activity, state) {
  return state?.my_submission?.answer ?? {};
}
function appendAnswerStatus(parent, state, locale = getLocale()) {
  if (!state?.my_submission)
    return;
  parent.append(text("p", state.my_submission.is_stale ? t("stale", locale) : t("saved", locale)));
}
function createSubmitButton(activity, state, locale = getLocale()) {
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = state?.my_submission && !state.my_submission.is_stale ? t("update", locale) : t("submit", locale);
  button.disabled = activity.state !== "open";
  return button;
}
function appendChoiceAnswer(parent, activity, state, kind, stateUrl, locale = getLocale()) {
  const form = document.createElement("form");
  const answer = answerFor(activity, state);
  const selected = selectedChoices(answer);
  const multiple = kind === "multiple_choice";
  for (const option of choicesFor(activity)) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = multiple ? "checkbox" : "radio";
    input.name = multiple ? "choices" : "choice";
    input.value = option.id;
    input.checked = selected.includes(option.id);
    input.disabled = activity.state !== "open";
    label.append(input, document.createTextNode(` ${option.text}`));
    form.append(label, document.createElement("br"));
  }
  const submit = createSubmitButton(activity, state, locale);
  if (activity.state === "open")
    form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = [...new FormData(form).getAll(multiple ? "choices" : "choice")].map(String);
    if (!values.length)
      return;
    const answerPayload = multiple ? { choices: values } : { choice: values[0] };
    submitAnswer(form, submitUrl(stateUrl, activity), answerPayload, submit, stateUrl, locale);
  });
  parent.append(form);
}
function appendTextAnswer(parent, activity, state, kind, stateUrl, locale = getLocale()) {
  const content = activityContent(activity);
  const form = document.createElement("form");
  const input = document.createElement(kind === "short_text" || kind === "word_cloud" ? "textarea" : "input");
  const field = kind === "numeric" ? "value" : kind === "rating" ? "rating" : "text";
  input.name = field;
  input.value = answerText(answerFor(activity, state), field);
  if (kind === "word_cloud") {
    input.placeholder = locale === "zh-Hans" ? "输入词语或短语…" : "Enter a word or phrase…";
  }
  if (input instanceof HTMLInputElement) {
    input.type = kind === "numeric" || kind === "rating" ? "number" : "text";
    const minimum = numberValue(content.minimum);
    const maximum = numberValue(content.maximum);
    const step = numberValue(content.step);
    if (minimum !== null)
      input.min = String(minimum);
    if (maximum !== null)
      input.max = String(maximum);
    if (step !== null)
      input.step = String(step);
  }
  input.disabled = activity.state !== "open";
  form.append(input);
  const submit = createSubmitButton(activity, state, locale);
  if (activity.state === "open")
    form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const raw = input.value.trim();
    if (!raw)
      return;
    const value = kind === "numeric" || kind === "rating" ? Number(raw) : raw;
    if (typeof value === "number" && !Number.isFinite(value))
      return;
    submitAnswer(form, submitUrl(stateUrl, activity), { [field]: value }, submit, stateUrl, locale);
  });
  parent.append(form);
}
function appendRankingAnswer(parent, activity, state, stateUrl, locale = getLocale()) {
  const form = document.createElement("form");
  const select = document.createElement("select");
  select.multiple = true;
  select.name = "ranking";
  const selected = selectedChoices(answerFor(activity, state));
  for (const option of choicesFor(activity)) {
    const element = document.createElement("option");
    element.value = option.id;
    element.textContent = option.text;
    element.selected = selected.includes(option.id);
    select.append(element);
  }
  select.disabled = activity.state !== "open";
  form.append(select);
  const submit = createSubmitButton(activity, state, locale);
  if (activity.state === "open")
    form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = [...select.selectedOptions].map((option) => option.value);
    if (!values.length)
      return;
    submitAnswer(form, submitUrl(stateUrl, activity), { ranking: values }, submit, stateUrl, locale);
  });
  parent.append(form);
}
async function submitAnswer(form, url, answer, button, stateUrl, locale = getLocale()) {
  button.disabled = true;
  let notice = form.querySelector("[data-liveclassroom-form-status]");
  if (!notice) {
    notice = document.createElement("p");
    notice.dataset.liveclassroomFormStatus = "true";
    notice.setAttribute("aria-live", "polite");
    form.append(notice);
  }
  try {
    await postJson(url, { answer });
    notice.textContent = t("saved", locale);
    window.setTimeout(() => void refreshMountedState(form.closest("[data-liveclassroom-app]"), stateUrl), 0);
  } catch (error) {
    notice.textContent = error instanceof Error ? error.message : t("unavailable", locale);
    button.disabled = false;
  }
}
function renderMedia(parent, activity) {
  const content = activityContent(activity);
  const mediaDisabled = content.media_disabled === true || activity.definition.media_disabled === true;
  if (mediaDisabled) {
    parent.append(text("p", "This media is unavailable."));
    return;
  }
  const url = stringValue(content.url, stringValue(activity.definition.url));
  if (!url)
    return;
  const rawMediaType = stringValue(content.media_type, stringValue(activity.definition.media_type)).toLowerCase();
  const caption = stringValue(content.caption, stringValue(activity.definition.caption));
  let mediaType = rawMediaType;
  const cleanUrl = url.split("?")[0].toLowerCase();
  if (!mediaType) {
    if (cleanUrl.match(/\.(png|jpe?g|svg|webp|gif)$/i)) {
      mediaType = "image";
    } else if (cleanUrl.match(/\.(mp4|webm)$/i)) {
      mediaType = "video";
    } else if (cleanUrl.match(/\.(mp3|ogg|wav)$/i)) {
      mediaType = "audio";
    } else {
      mediaType = "iframe";
    }
  }
  const container = document.createElement("div");
  container.className = "lc-media-container";
  if (mediaType === "image" || cleanUrl.match(/\.(png|jpe?g|svg|webp|gif)$/i)) {
    const img = document.createElement("img");
    img.src = url;
    img.alt = caption || "Media image";
    img.style.maxWidth = "100%";
    img.style.borderRadius = "8px";
    container.append(img);
  } else if (mediaType === "video" || cleanUrl.match(/\.(mp4|webm)$/i)) {
    const video = document.createElement("video");
    video.controls = true;
    video.src = url;
    video.style.maxWidth = "100%";
    container.append(video);
  } else if (mediaType === "audio" || cleanUrl.match(/\.(mp3|ogg|wav)$/i)) {
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.src = url;
    container.append(audio);
  } else {
    const iframe = document.createElement("iframe");
    const provider = stringValue(content.provider, stringValue(activity.definition.provider)).toLowerCase();
    iframe.src = url;
    iframe.sandbox.value = provider === "vaultpub" ? "allow-scripts allow-same-origin" : "allow-scripts";
    iframe.referrerPolicy = provider === "vaultpub" ? "same-origin" : "no-referrer";
    iframe.allow = "";
    iframe.loading = "lazy";
    iframe.title = caption || (provider === "vaultpub" ? "VaultPub presentation" : "Embedded content");
    iframe.style.width = "100%";
    iframe.style.minHeight = "400px";
    iframe.style.border = "none";
    iframe.style.borderRadius = "8px";
    container.append(iframe);
  }
  if (caption) {
    const figcaption = document.createElement("p");
    figcaption.className = "lc-media-caption";
    figcaption.textContent = caption;
    container.append(figcaption);
  }
  parent.append(container);
}
var activeTimerStartTimes = new Map;
function renderTimer(parent, activity, audience, locale) {
  const content = activityContent(activity);
  const duration = numberValue(content.duration_seconds) ?? numberValue(activity.definition.duration_seconds) ?? 60;
  const label = stringValue(content.label, stringValue(activity.definition.label, t("timer", locale)));
  const container = document.createElement("div");
  container.className = "lc-timer-display";
  if (label) {
    const labelEl = document.createElement("div");
    labelEl.className = "lc-timer-label";
    labelEl.textContent = label;
    container.append(labelEl);
  }
  const countdownEl = document.createElement("div");
  countdownEl.className = "lc-timer-countdown";
  const totalDurationEl = document.createElement("div");
  totalDurationEl.className = "lc-timer-subtext";
  totalDurationEl.textContent = `${t("timerRemaining", locale)} (${duration}${t("seconds", locale)})`;
  container.append(countdownEl, totalDurationEl);
  parent.append(container);
  const timerKey = `timer_${activity.id}_${activity.revision}`;
  let startTime = activeTimerStartTimes.get(timerKey);
  if (!startTime) {
    startTime = Date.now();
    activeTimerStartTimes.set(timerKey, startTime);
  }
  const updateDisplay = () => {
    if (!countdownEl.isConnected)
      return false;
    let remaining = 0;
    if (activity.state === "open") {
      const elapsed = Math.floor((Date.now() - startTime) / 1000);
      remaining = Math.max(0, duration - elapsed);
    } else if (activity.state === "closed") {
      remaining = 0;
    } else {
      remaining = duration;
    }
    const mm = String(Math.floor(remaining / 60)).padStart(2, "0");
    const ss = String(remaining % 60).padStart(2, "0");
    if (remaining <= 0) {
      countdownEl.textContent = "00:00";
      countdownEl.classList.add("lc-timer-ended");
      totalDurationEl.textContent = t("timerFinished", locale);
      totalDurationEl.classList.add("lc-timer-ended-text");
      return false;
    } else {
      countdownEl.textContent = `${mm}:${ss}`;
      return true;
    }
  };
  const initialRun = updateDisplay();
  if (activity.state === "open" && initialRun) {
    const interval = window.setInterval(() => {
      const keepTicking = updateDisplay();
      if (!keepTicking) {
        window.clearInterval(interval);
      }
    }, 1000);
  }
}
function renderWordCloud(parent, aggregate, locale, isTeacher = false) {
  const container = document.createElement("div");
  container.className = "lc-word-cloud";
  const wordMap = aggregate?.word_frequencies ?? aggregate?.words ?? {};
  const entries = Object.entries(wordMap);
  if (!entries.length) {
    container.append(text("p", t("noResponses", locale)));
    parent.append(container);
    return;
  }
  let minCount = Infinity;
  let maxCount = -Infinity;
  for (const [, count] of entries) {
    const num = Number(count) || 1;
    if (num < minCount)
      minCount = num;
    if (num > maxCount)
      maxCount = num;
  }
  if (!Number.isFinite(minCount))
    minCount = 1;
  if (!Number.isFinite(maxCount))
    maxCount = 1;
  const tagsContainer = document.createElement("div");
  tagsContainer.className = "lc-word-cloud-tags";
  const sorted = [...entries].sort((a, b) => (Number(b[1]) || 0) - (Number(a[1]) || 0) || a[0].localeCompare(b[0]));
  for (const [word, countVal] of sorted) {
    const count = Number(countVal) || 1;
    const tag = document.createElement("span");
    tag.className = "lc-word-tag";
    const fontSize = maxCount === minCount ? 18 : Math.round(14 + (count - minCount) / (maxCount - minCount) * (36 - 14));
    tag.style.fontSize = `${fontSize}px`;
    tag.textContent = `${word} (${count})`;
    tag.title = `${word}: ${count}`;
    tagsContainer.append(tag);
  }
  container.append(tagsContainer);
  if (isTeacher) {
    const rawAnswers = aggregate?.raw_answers ?? aggregate?.values ?? [];
    if (rawAnswers.length > 0) {
      const moderationSection = document.createElement("div");
      moderationSection.className = "lc-word-cloud-moderation";
      const modHeading = document.createElement("h4");
      modHeading.textContent = `${t("moderation", locale)} (${rawAnswers.length})`;
      moderationSection.append(modHeading);
      const list = document.createElement("ul");
      list.className = "lc-moderation-list";
      for (const item of rawAnswers) {
        list.append(text("li", displayAnswer(item)));
      }
      moderationSection.append(list);
      container.append(moderationSection);
    }
  }
  parent.append(container);
}
function renderAggregate(parent, aggregate, locale = getLocale()) {
  if (!aggregate)
    return;
  const count = aggregate.submission_count;
  const summary = typeof count === "number" ? `${count} ${locale === "zh-Hans" ? "人作答" : count === 1 ? "response" : "responses"}` : t("results", locale);
  parent.append(text("p", summary));
  if (aggregate.choices) {
    const entries = Object.entries(aggregate.choices);
    let totalVotes = 0;
    for (const [, v] of entries)
      totalVotes += Number(v) || 0;
    const barsContainer = document.createElement("div");
    barsContainer.className = "lc-choice-bars";
    for (const [choice, value] of entries) {
      const voteCount = Number(value) || 0;
      const pct = totalVotes > 0 ? Math.round(voteCount / totalVotes * 100) : 0;
      const row = document.createElement("div");
      row.className = "lc-choice-bar-row";
      const header = document.createElement("div");
      header.className = "lc-choice-bar-header";
      header.append(text("strong", choice), text("span", `${pct}% (${voteCount} ${voteCount === 1 ? t("vote", locale) : t("votes", locale)})`));
      const barContainer = document.createElement("div");
      barContainer.className = "lc-bar-container";
      const bar = document.createElement("div");
      bar.className = "lc-bar";
      bar.style.width = `${pct}%`;
      const barText = document.createElement("span");
      barText.className = "lc-bar-text";
      barText.textContent = `${pct}% (${voteCount} ${locale === "zh-Hans" ? "票" : "votes"})`;
      barContainer.append(bar, barText);
      row.append(header, barContainer);
      barsContainer.append(row);
    }
    parent.append(barsContainer);
  }
  if (aggregate.words || aggregate.word_frequencies) {
    renderWordCloud(parent, aggregate, locale, false);
  }
  if (aggregate.values?.length && !aggregate.words && !aggregate.word_frequencies) {
    const values = document.createElement("ul");
    for (const value of aggregate.values)
      values.append(text("li", displayAnswer(value)));
    parent.append(values);
  }
}
function renderActivity(parent, activity, audience, state, stateUrl, aggregate, rootLocale) {
  const locale = rootLocale ?? getLocale(parent.closest("[data-liveclassroom-app]"));
  parent.replaceChildren();
  if (!activity) {
    parent.append(text("p", audience === "student" ? t("waiting", locale) : t("noActivityPublished", locale)));
    return;
  }
  const definition = activity.definition;
  parent.append(text("h2", stringValue(definition.title, stringValue(definition.kind, t("activity", locale)))));
  const kind = activityKind(activity);
  if (kind === "timer") {
    renderTimer(parent, activity, audience, locale);
    if (audience === "teacher") {
      parent.append(text("p", `${t("state", locale)}: ${activity.state}; ${t("revision", locale)} ${activity.revision}`));
    }
    return;
  }
  if (kind === "media") {
    appendPrompt(parent, activity);
    renderMedia(parent, activity);
    if (audience === "teacher") {
      parent.append(text("p", `${t("state", locale)}: ${activity.state}; ${t("revision", locale)} ${activity.revision}`));
    }
    return;
  }
  if (kind === "markdown") {
    const content = activityContent(activity);
    const md = stringValue(content.markdown, stringValue(activity.definition.markdown, questionPrompt(activity)));
    if (md) {
      parent.append(renderMarkdownText(md));
    } else {
      appendPrompt(parent, activity);
    }
    if (audience === "teacher") {
      parent.append(text("p", `${t("state", locale)}: ${activity.state}; ${t("revision", locale)} ${activity.revision}`));
    }
    return;
  }
  appendPrompt(parent, activity);
  const responseKinds = [
    "single_choice",
    "multiple_choice",
    "true_false",
    "poll",
    "short_text",
    "word_cloud",
    "numeric",
    "rating",
    "ranking"
  ];
  if (audience === "student" && state && stateUrl && state.participant?.admission_state === "admitted") {
    const content = activityContent(activity);
    const hasVisibleContent = questionPrompt(activity) !== "" || choicesFor(activity).length > 0 || stringValue(content.markdown, stringValue(activity.definition.markdown)) !== "";
    if (responseKinds.includes(kind) && !hasVisibleContent) {
      parent.append(text("p", t("notShownYet", locale)));
    } else if (["single_choice", "multiple_choice", "true_false", "poll"].includes(kind)) {
      appendChoiceAnswer(parent, activity, state, kind, stateUrl, locale);
    } else if (["short_text", "word_cloud", "numeric", "rating"].includes(kind)) {
      appendTextAnswer(parent, activity, state, kind, stateUrl, locale);
    } else if (kind === "ranking") {
      appendRankingAnswer(parent, activity, state, stateUrl, locale);
    } else {
      parent.append(text("p", t("noAnswer", locale)));
    }
    appendAnswerStatus(parent, state, locale);
  }
  if (audience !== "student") {
    if (kind === "word_cloud") {
      renderWordCloud(parent, aggregate ?? state?.aggregate ?? null, locale, audience === "teacher");
    } else {
      appendChoicePresentation(parent, activity);
    }
  }
  if (audience !== "student" || state?.participant?.admission_state === "admitted") {
    appendRevealedFeedback(parent, activity, locale);
  }
  if ((audience === "display" || audience === "teacher") && kind !== "word_cloud") {
    renderAggregate(parent, aggregate ?? state?.aggregate ?? null, locale);
  }
  if (audience === "teacher") {
    parent.append(text("p", `${t("state", locale)}: ${activity.state}; ${t("revision", locale)} ${activity.revision}`));
  }
}
function setStatus(root, message) {
  const status = root.querySelector("[data-liveclassroom-status]");
  if (status)
    status.textContent = message;
}
function channelState(state, channel) {
  return state.channels?.[channel] ?? null;
}
function button(label, disabled = false) {
  const control = document.createElement("button");
  control.type = "button";
  control.textContent = label;
  control.disabled = disabled;
  return control;
}
function bindCommand(control, command) {
  if (!control || control.dataset.liveclassroomCommandBound === "true")
    return;
  control.dataset.liveclassroomCommandBound = "true";
  control.addEventListener("click", command);
}
function actionUrl(stateUrl, suffix) {
  return apiEndpoint(stateUrl, suffix);
}
async function ensureStudentJoin(root) {
  const locale = getLocale(root);
  if (root.dataset.audience !== "student")
    return true;
  if (root.dataset.joined === "true")
    return true;
  const pendingName = root.dataset.pendingName?.trim() ?? "";
  const authenticated = root.dataset.authenticated === "true";
  const accessMode = root.dataset.accessMode ?? "guest";
  const guestJoinUrl = root.dataset.guestJoinUrl;
  const accountJoinUrl = root.dataset.accountJoinUrl;
  if (authenticated && accessMode !== "guest" && accountJoinUrl) {
    await postJson(accountJoinUrl, {}, `join-account-${root.dataset.sessionId ?? "session"}`);
    root.dataset.joined = "true";
    return true;
  }
  if (pendingName && accessMode !== "authenticated" && guestJoinUrl) {
    await postJson(guestJoinUrl, { display_name: pendingName }, `join-guest-${root.dataset.sessionId ?? "session"}`);
    root.dataset.joined = "true";
    return true;
  }
  if (!authenticated && accessMode === "authenticated")
    return false;
  if (guestJoinUrl && accessMode !== "authenticated") {
    let prompt = root.querySelector("[data-liveclassroom-join-prompt]");
    if (!prompt) {
      prompt = document.createElement("form");
      prompt.dataset.liveclassroomJoinPrompt = "true";
      const label = document.createElement("label");
      label.textContent = `${t("displayName", locale)} `;
      const input = document.createElement("input");
      input.name = "display_name";
      input.required = true;
      input.maxLength = 100;
      const submit = button(t("joinClassroom", locale));
      label.append(input);
      prompt.append(label, submit);
      prompt.addEventListener("submit", (event) => {
        event.preventDefault();
        const name = input.value.trim();
        if (!name)
          return;
        root.dataset.pendingName = name;
        prompt?.remove();
        refreshMountedState(root, root.dataset.stateUrl);
      });
      (root.querySelector("[data-liveclassroom-content]") ?? root).prepend(prompt);
    }
  }
  return false;
}
async function execute(root, url, body = {}) {
  const locale = getLocale(root);
  const key = `${root.dataset.sessionId ?? "session"}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  try {
    await postJson(url, body, key);
    setStatus(root, t("updated", locale));
    await refreshMountedState(root, root.dataset.stateUrl);
  } catch (error) {
    setStatus(root, error instanceof Error ? error.message : t("unavailable", locale));
  }
}
function addCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = String(value ?? "");
  row.append(cell);
}
function emptyRow(message, columns) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = columns;
  cell.textContent = message;
  row.append(cell);
  return row;
}
function renderTeacherAnalytics(root, data, currentActivityId) {
  const locale = getLocale(root);
  const attendance = record(data.attendance);
  const summary = root.querySelector("#analytics-summary");
  if (summary) {
    summary.textContent = `${attendance.admitted ?? 0} ${t("admitted", locale)} · ${attendance.currently_connected ?? 0} ${t("connected", locale)} · ${attendance.ever_connected ?? 0} ${t("attended", locale)} · ${attendance.pending ?? 0} ${t("pending", locale)}`;
  }
  const activities = Array.isArray(data.activities) ? data.activities.map(record) : [];
  const activityBody = root.querySelector("#analytics-activities");
  if (activityBody) {
    activityBody.replaceChildren();
    if (!activities.length)
      activityBody.append(emptyRow(locale === "zh-Hans" ? "暂无活动。" : "No activities yet.", 6));
    for (const activity of activities) {
      const row = document.createElement("tr");
      addCell(row, activity.sequence);
      addCell(row, activity.title || activity.kind);
      addCell(row, `${activity.submitted_count ?? 0}/${activity.eligible_participant_count ?? 0}`);
      addCell(row, `${activity.response_rate ?? 0}%`);
      addCell(row, activity.stale_submission_count ?? 0);
      addCell(row, activity.state);
      activityBody.append(row);
    }
  }
  const participantBody = root.querySelector("#analytics-participants");
  const participants = Array.isArray(data.participants) ? data.participants.map(record) : [];
  if (participantBody) {
    participantBody.replaceChildren();
    if (!participants.length)
      participantBody.append(emptyRow(locale === "zh-Hans" ? "暂无学生。" : "No participants yet.", 5));
    for (const participant of participants) {
      const row = document.createElement("tr");
      addCell(row, participant.display_name);
      addCell(row, participant.admission_state);
      addCell(row, participant.current_response_count ?? 0);
      addCell(row, participant.stale_response_count ?? 0);
      const connStatus = participant.connected_at ? participant.disconnected_at ? t("offline", locale) : t("connected", locale) : t("notConnected", locale);
      addCell(row, connStatus);
      participantBody.append(row);
    }
  }
  const current = activities.find((activity) => activity.id === currentActivityId);
  const caption = root.querySelector("#analytics-responses-caption");
  if (caption) {
    caption.textContent = current ? `${locale === "zh-Hans" ? "作答详情：" : "Responses for "}${current.title || current.kind}` : locale === "zh-Hans" ? "当前活动作答详情" : "Responses for the current activity";
  }
  const responseBody = root.querySelector("#analytics-responses");
  if (responseBody) {
    responseBody.replaceChildren();
    const responses = current && Array.isArray(current.responses) ? current.responses.map(record) : [];
    if (!current || !responses.length) {
      responseBody.append(emptyRow(current ? locale === "zh-Hans" ? "暂无作答。" : "No responses yet." : locale === "zh-Hans" ? "发布活动后可在此查看学生作答。" : "Publish an activity to review responses.", 4));
    }
    for (const response of responses) {
      const row = document.createElement("tr");
      addCell(row, response.display_name);
      addCell(row, JSON.stringify(response.answer ?? {}));
      addCell(row, response.revision ?? "-");
      addCell(row, response.is_stale ? locale === "zh-Hans" ? "已过期" : "Stale" : locale === "zh-Hans" ? "最新" : "Current");
      responseBody.append(row);
    }
  }
  const resultSummary = root.querySelector("#result-summary");
  if (resultSummary) {
    resultSummary.replaceChildren();
    if (!current) {
      resultSummary.append(text("p", t("noActivityPublished", locale)));
    } else {
      const rateBadge = document.createElement("div");
      rateBadge.className = "lc-rate-badge";
      rateBadge.textContent = `${t("responseRate", locale)}: ${current.response_rate ?? 0}% (${current.submitted_count ?? 0}/${current.eligible_participant_count ?? 0})`;
      resultSummary.append(rateBadge);
      const aggregate = record(current.aggregate);
      const choices = record(aggregate.choices);
      const choiceEntries = Object.entries(choices);
      if (choiceEntries.length > 0) {
        let totalVotes = 0;
        for (const [, count] of choiceEntries)
          totalVotes += Number(count) || 0;
        const barsContainer = document.createElement("div");
        barsContainer.className = "lc-choice-bars";
        for (const [choice, countVal] of choiceEntries) {
          const voteCount = Number(countVal) || 0;
          const pct = totalVotes > 0 ? Math.round(voteCount / totalVotes * 100) : 0;
          const row = document.createElement("div");
          row.className = "lc-choice-bar-row";
          const header = document.createElement("div");
          header.className = "lc-choice-bar-header";
          header.append(text("strong", choice), text("span", `${pct}% (${voteCount} ${voteCount === 1 ? t("vote", locale) : t("votes", locale)})`));
          const barContainer = document.createElement("div");
          barContainer.className = "lc-bar-container";
          const bar = document.createElement("div");
          bar.className = "lc-bar";
          bar.style.width = `${pct}%`;
          const barText = document.createElement("span");
          barText.className = "lc-bar-text";
          barText.textContent = `${pct}% (${voteCount} ${locale === "zh-Hans" ? "票" : "votes"})`;
          barContainer.append(bar, barText);
          row.append(header, barContainer);
          barsContainer.append(row);
        }
        resultSummary.append(barsContainer);
      } else if (aggregate.words || aggregate.word_frequencies) {
        renderWordCloud(resultSummary, aggregate, locale, true);
      } else {
        resultSummary.append(text("p", `${current.submitted_count ?? 0} ${locale === "zh-Hans" ? "人已提交" : "submitted"}`));
      }
    }
  }
}
function renderChat(root, state, stateUrl) {
  const locale = getLocale(root);
  const audience = root.dataset.audience ?? "student";
  const host = root.querySelector("[data-liveclassroom-chat]");
  if (!host)
    return;
  const status = host.querySelector("[data-liveclassroom-chat-status]");
  const messages = host.querySelector("[data-liveclassroom-chat-messages]");
  const form = host.querySelector("[data-liveclassroom-chat-form]");
  const input = form?.querySelector("textarea[name=body]");
  const send = form?.querySelector("button[type=submit]");
  const settings = host.querySelector("[data-liveclassroom-chat-settings]");
  const chatHeading = host.querySelector("#chat-heading, h2");
  if (chatHeading)
    chatHeading.textContent = t("chat", locale);
  if (status)
    status.textContent = state.enabled ? "" : t("chatDisabled", locale);
  if (messages) {
    messages.replaceChildren();
    if (!state.messages.length)
      messages.append(text("li", state.enabled ? t("noMessages", locale) : t("chatDisabled", locale)));
    for (const message of state.messages) {
      const item = document.createElement("li");
      item.append(text("strong", `${stringValue(message.display_name)}: `), text("span", message.body));
      messages.append(item);
    }
  }
  if (form && input && send) {
    send.textContent = t("send", locale);
    form.hidden = audience === "student" ? !state.enabled : false;
    input.disabled = !state.enabled;
    send.disabled = !state.enabled;
    if (form.dataset.liveclassroomChatBound !== "true") {
      form.dataset.liveclassroomChatBound = "true";
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const body = input.value.trim();
        if (!body)
          return;
        send.disabled = true;
        postJson(actionUrl(stateUrl, "sessions/chat/send"), { body }, `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`).then(() => {
          input.value = "";
          return refreshMountedState(root, stateUrl);
        }).catch((error) => {
          if (status)
            status.textContent = error instanceof Error ? error.message : t("chatUnavailable", locale);
          send.disabled = false;
        });
      });
    }
  }
  if (audience !== "teacher" || !settings)
    return;
  let toggle = settings.querySelector("input[type=checkbox]");
  let toggleLabel = settings.querySelector("label");
  if (!toggle) {
    toggleLabel = document.createElement("label");
    toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggleLabel.append(toggle, document.createTextNode(` ${t("enableChat", locale)}`));
    settings.append(toggleLabel);
    toggle.addEventListener("change", () => void execute(root, actionUrl(stateUrl, "sessions/chat/settings"), { enabled: toggle?.checked ?? false }));
  } else if (toggleLabel) {
    toggleLabel.lastChild?.remove();
    toggleLabel.append(document.createTextNode(` ${t("enableChat", locale)}`));
  }
  toggle.checked = state.enabled;
}
async function refreshChat(root, stateUrl) {
  const locale = getLocale(root);
  try {
    const chat = await getJson(actionUrl(stateUrl, "sessions/chat"));
    renderChat(root, chat, stateUrl);
  } catch {
    const status = root.querySelector("[data-liveclassroom-chat-status]");
    if (status)
      status.textContent = t("chatUnavailable", locale);
  }
}
function renderStudentHistory(root, stateUrl) {
  const locale = getLocale(root);
  const host = root.querySelector("[data-liveclassroom-history]");
  if (!host || host.dataset.liveclassroomHistoryLoaded === "true")
    return;
  host.dataset.liveclassroomHistoryLoaded = "true";
  getJson(actionUrl(stateUrl, "sessions/history")).then((data) => {
    host.replaceChildren(text("h2", t("history", locale)));
    if (!data.activities.length) {
      host.append(text("p", t("noHistory", locale)));
      return;
    }
    const list = document.createElement("ul");
    for (const activity of data.activities) {
      const item = document.createElement("li");
      item.append(text("strong", stringValue(activity.definition.title, t("activity", locale))));
      const prompt = questionPrompt(activity);
      if (prompt)
        item.append(text("span", `: ${prompt}`));
      list.append(item);
    }
    host.append(list);
  }).catch(() => {
    host.replaceChildren(text("p", t("historyUnavailable", locale)));
  });
}
async function refreshTeacherAnalytics(root, state, stateUrl) {
  const locale = getLocale(root);
  try {
    const data = await getJson(actionUrl(stateUrl, "sessions/analytics"));
    renderTeacherAnalytics(root, data, state.current_activity?.id ?? null);
  } catch {
    const summary = root.querySelector("#analytics-summary");
    if (summary)
      summary.textContent = t("analyticsUnavailable", locale);
  }
}
function renderTeacherControls(root, state, stateUrl) {
  const locale = getLocale(root);
  const actionHost = root.querySelector("[data-liveclassroom-teacher-controls]") ?? (() => {
    const host = document.createElement("section");
    host.dataset.liveclassroomTeacherControls = "true";
    host.setAttribute("aria-label", t("controls", locale));
    root.prepend(host);
    return host;
  })();
  actionHost.replaceChildren();
  const lifecycle = document.createElement("div");
  lifecycle.className = "lc-actions";
  const status = state.session.status;
  const activity = state.current_activity;
  const activityStatus = root.querySelector("#activity-status");
  if (activityStatus) {
    activityStatus.textContent = activity ? `${stringValue(activity.definition.title, stringValue(activity.definition.kind, t("activity", locale)))} (${activity.state})` : t("noActivityPublished", locale);
  }
  const existingStart = root.querySelector("#start-session");
  const existingPause = root.querySelector("#pause-session");
  const existingEnd = root.querySelector("#end-session");
  if (existingStart)
    existingStart.textContent = t("start", locale);
  if (existingPause)
    existingPause.textContent = t("pause", locale);
  if (existingEnd)
    existingEnd.textContent = t("end", locale);
  if (!existingStart && !existingPause && !existingEnd) {
    const startControl = button(t("start", locale), ["live", "ended"].includes(status));
    const pauseControl = button(t("pause", locale), status !== "live");
    const endControl = button(t("end", locale), status === "ended");
    lifecycle.append(startControl, pauseControl, endControl);
    startControl.addEventListener("click", () => void execute(root, actionUrl(stateUrl, "sessions/start")));
    pauseControl.addEventListener("click", () => void execute(root, actionUrl(stateUrl, "sessions/pause")));
    endControl.addEventListener("click", () => {
      if (window.confirm(t("confirmEnd", locale))) {
        execute(root, actionUrl(stateUrl, "sessions/end"));
      }
    });
    actionHost.append(lifecycle);
  } else {
    if (existingStart)
      existingStart.disabled = ["live", "ended"].includes(status);
    if (existingPause)
      existingPause.disabled = status !== "live";
    if (existingEnd)
      existingEnd.disabled = status === "ended";
    bindCommand(existingStart, () => void execute(root, actionUrl(stateUrl, "sessions/start")));
    bindCommand(existingPause, () => void execute(root, actionUrl(stateUrl, "sessions/pause")));
    bindCommand(existingEnd, () => {
      if (window.confirm(t("confirmEnd", locale))) {
        execute(root, actionUrl(stateUrl, "sessions/end"));
      }
    });
  }
  for (const item of root.querySelectorAll(".lc-item[data-item-id]")) {
    if (item.dataset.liveclassroomBound === "true")
      continue;
    item.dataset.liveclassroomBound = "true";
    item.addEventListener("click", () => {
      const itemId = numberValue(item.dataset.itemId);
      if (itemId !== null)
        execute(root, actionUrl(stateUrl, "sessions/activities"), { flow_item_id: itemId });
    });
  }
  if (!activity)
    return;
  const activityActions = document.createElement("div");
  activityActions.className = "lc-actions";
  const existingClose = root.querySelector("#close-activity");
  const existingReveal = root.querySelector("#reveal-activity");
  if (existingClose)
    existingClose.textContent = t("close", locale);
  if (existingReveal)
    existingReveal.textContent = t("reveal", locale);
  if (!existingClose && !existingReveal) {
    const closeControl = button(t("close", locale), activity.state !== "open");
    const revealControl = button(t("reveal", locale), activity.state !== "closed");
    activityActions.append(closeControl, revealControl);
    closeControl.addEventListener("click", () => void execute(root, actionUrl(stateUrl, `activities/${activity.id}/close`)));
    revealControl.addEventListener("click", () => void execute(root, actionUrl(stateUrl, `activities/${activity.id}/reveal`)));
    actionHost.append(activityActions);
  } else {
    if (existingClose)
      existingClose.disabled = activity.state !== "open";
    if (existingReveal)
      existingReveal.disabled = activity.state !== "closed";
    bindCommand(existingClose, () => void execute(root, actionUrl(stateUrl, `activities/${activity.id}/close`)));
    bindCommand(existingReveal, () => void execute(root, actionUrl(stateUrl, `activities/${activity.id}/reveal`)));
  }
  const channels = document.createElement("div");
  channels.className = "lc-actions";
  for (const channel of ["display", "participants"]) {
    const publish = button(`${t("publish", locale)} · ${channel === "display" ? t("display", locale) : t("participants", locale)}`);
    publish.addEventListener("click", () => void execute(root, actionUrl(stateUrl, "sessions/channels/publish"), {
      channel,
      activity_id: activity.id
    }));
    channels.append(publish);
  }
  actionHost.append(channels);
  const visibility = document.createElement("fieldset");
  visibility.append(text("legend", t("audienceVisibility", locale)));
  const participantChannel = channelState(state, "participants");
  const currentVisibility = participantChannel?.visibility ?? {
    show_prompt: true,
    show_aggregate: false,
    show_answer: false,
    show_explanation: false,
    show_own_status: true,
    allow_review: false
  };
  const visibilityFields = [
    ["show_prompt", t("showPrompt", locale)],
    ["show_aggregate", t("showAggregate", locale)],
    ["show_answer", t("showAnswer", locale)],
    ["show_explanation", t("showExplanation", locale)],
    ["show_own_status", t("showOwnStatus", locale)],
    ["allow_review", t("allowReview", locale)]
  ];
  for (const [field, label] of visibilityFields) {
    const wrapper = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = currentVisibility[field];
    checkbox.addEventListener("change", () => void execute(root, actionUrl(stateUrl, "sessions/channels/settings"), {
      channel: "participants",
      [field]: checkbox.checked
    }));
    wrapper.append(checkbox, document.createTextNode(` ${label}`));
    visibility.append(wrapper, document.createElement("br"));
  }
  actionHost.append(visibility);
}
function renderAdmission(root, participants, stateUrl) {
  const locale = getLocale(root);
  const pending = participants.filter((participant) => participant.admission_state === "pending");
  const existing = root.querySelector("[data-liveclassroom-admission]") ?? (() => {
    const host = document.createElement("section");
    host.dataset.liveclassroomAdmission = "true";
    root.append(host);
    return host;
  })();
  existing.replaceChildren();
  if (!pending.length)
    return;
  existing.append(text("h2", `${t("participants", locale)} (${pending.length} ${t("pending", locale)})`));
  for (const participant of pending) {
    const participantId = numberValue(participant.id);
    if (participantId === null)
      continue;
    const admit = button(`${t("admit", locale)} ${stringValue(participant.display_name)}`);
    admit.addEventListener("click", () => void execute(root, actionUrl(stateUrl, `sessions/participants/${participantId}/admission`), { admitted: true }));
    existing.append(admit);
  }
}
async function refreshTeacher(root, state, stateUrl) {
  const locale = getLocale(root);
  const content = root.querySelector("[data-liveclassroom-content]");
  if (content) {
    renderActivity(content, state.current_activity, "teacher", state, stateUrl, null, locale);
  }
  const participantPreview = root.querySelector("[data-liveclassroom-participant-preview]");
  const participantState = channelState(state, "participants");
  if (participantPreview) {
    renderActivity(participantPreview, participantState?.activity ?? null, "student", state, stateUrl, participantState?.aggregate, locale);
  }
  renderTeacherControls(root, state, stateUrl);
  try {
    const participants = await getJson(actionUrl(stateUrl, "sessions/participants"));
    renderAdmission(root, participants.participants, stateUrl);
  } catch {
    renderAdmission(root, [], stateUrl);
  }
}
async function refreshMountedState(root, explicitStateUrl) {
  if (!root)
    return;
  const locale = getLocale(root);
  mountLanguageSwitcher(root, () => {
    refreshMountedState(root, explicitStateUrl ?? root.dataset.stateUrl);
  });
  const audience = root.dataset.audience ?? "student";
  const stateUrl = explicitStateUrl ?? root.dataset.stateUrl;
  if (!stateUrl)
    return;
  try {
    if (!await ensureStudentJoin(root)) {
      if (audience === "student") {
        setStatus(root, root.dataset.accessMode === "authenticated" && root.dataset.authenticated !== "true" ? t("signInRequired", locale) : t("enterDisplayName", locale));
      }
      return;
    }
    const channel = audience === "display" ? "display" : audience === "teacher" ? "display" : "participants";
    const state = await getJson(`${stateUrl}${stateUrl.includes("?") ? "&" : "?"}channel=${channel}`);
    const content = root.querySelector("[data-liveclassroom-content]");
    if (content && audience !== "teacher") {
      if (audience === "student" && state.participant && state.participant.admission_state !== "admitted") {
        content.replaceChildren(text("p", t("waitingAdmission", locale)));
      } else {
        renderActivity(content, state.current_activity, audience, state, stateUrl, null, locale);
      }
      const heading = root.querySelector(audience === "display" ? "#display-title" : "#student-title");
      if (heading && state.current_activity) {
        heading.textContent = stringValue(state.current_activity.definition.title, state.session.title);
      }
    } else if (audience === "teacher") {
      await refreshTeacher(root, state, stateUrl);
      const sessionStatus = root.querySelector("#session-status");
      if (sessionStatus)
        sessionStatus.textContent = state.session.status;
      await refreshTeacherAnalytics(root, state, stateUrl);
    }
    if (audience === "teacher" || audience === "student" && state.participant?.admission_state === "admitted") {
      await refreshChat(root, stateUrl);
    }
    if (audience === "student" && state.participant?.admission_state === "admitted") {
      renderStudentHistory(root, stateUrl);
    }
    setStatus(root, `${state.session.status} · ${t("state", locale)} ${state.state_version}`);
  } catch (error) {
    setStatus(root, error instanceof Error ? error.message : t("unavailable", locale));
  }
}
function connect(root, refresh) {
  const path = root.dataset.websocketUrl;
  if (!path)
    return;
  let retry = 1000;
  const open = () => {
    const socket = new WebSocket(websocketUrl(path));
    socket.onopen = () => {
      retry = 1000;
    };
    socket.onmessage = () => void refresh();
    socket.onerror = () => socket.close();
    socket.onclose = () => {
      const locale = getLocale(root);
      setStatus(root, locale === "zh-Hans" ? "正在重新连接…" : "Reconnecting…");
      window.setTimeout(open, retry);
      retry = Math.min(retry * 2, 30000);
    };
  };
  open();
}
async function mount(root) {
  const stateUrl = root.dataset.stateUrl;
  if (!stateUrl)
    return;
  mountLanguageSwitcher(root, () => {
    refreshMountedState(root, stateUrl);
  });
  let refreshing = false;
  const refresh = async () => {
    if (refreshing)
      return;
    refreshing = true;
    try {
      await refreshMountedState(root, stateUrl);
    } finally {
      refreshing = false;
    }
  };
  connect(root, refresh);
  await refresh();
  window.setInterval(() => void refresh(), 3000);
}
if (typeof document !== "undefined") {
  for (const element of document.querySelectorAll("[data-liveclassroom-app]"))
    mount(element);
  for (const element of document.querySelectorAll("[data-liveclassroom-builder]"))
    mountBuilder(element);
  for (const element of document.querySelectorAll("[data-liveclassroom-ai-chat]"))
    mountAiChat(element);
}
export {
  renderWordCloud,
  renderTimer,
  renderTeacherAnalytics,
  renderMedia,
  renderMarkdownText,
  renderAggregate,
  renderActivity,
  refreshMountedState,
  mountLanguageSwitcher,
  mountBuilder,
  mountAiChat,
  mount,
  labels,
  getLabels
};
