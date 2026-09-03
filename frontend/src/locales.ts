export type Locale = "en" | "zh-Hans";

export const translations = {
  en: {
    // General
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

    // Student interaction
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

    // Teacher controls & lifecycle
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

    // Channel visibility
    audienceVisibility: "Audience visibility",
    showPrompt: "Show prompt",
    showAggregate: "Show aggregate",
    showAnswer: "Show answer",
    showExplanation: "Show explanation",
    showOwnStatus: "Show response status",
    allowReview: "Allow review",

    // Admission
    admit: "Admit",
    pending: "pending",

    // Chat
    chat: "Class chat",
    chatDisabled: "Chat is disabled.",
    chatUnavailable: "Chat is unavailable.",
    send: "Send",
    enableChat: "Enable chat",
    noMessages: "No messages yet.",

    // Analytics
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

    // Activity types & special renderers
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

    // Visual Builder
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

    // AI Assistant
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
    duplicateFlowPrompt: "Enter title for the duplicated flow:",
  },
  "zh-Hans": {
    // 通用
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

    // 学生端交互
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

    // 教师端控制与生命周期
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

    // 频道可见性
    audienceVisibility: "受众可见性设置",
    showPrompt: "显示题目",
    showAggregate: "显示统计结果",
    showAnswer: "显示正确答案",
    showExplanation: "显示解析",
    showOwnStatus: "显示作答状态",
    allowReview: "允许回顾",

    // 准入审核
    admit: "准入",
    pending: "待审核",

    // 讨论区
    chat: "课堂讨论",
    chatDisabled: "讨论区已关闭。",
    chatUnavailable: "讨论区不可用。",
    send: "发送",
    enableChat: "开启讨论区",
    noMessages: "暂无发言。",

    // 统计与分析
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

    // 活动类型与特殊渲染
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

    // 可视化流构建器
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

    // AI 辅助设计
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
    duplicateFlowPrompt: "请输入复制后的流程标题：",
  },
} as const;

export type TranslationKey = keyof typeof translations.en;

export function getLocale(root?: HTMLElement | null): Locale {
  if (root?.dataset.locale === "zh-Hans" || root?.dataset.locale === "zh") return "zh-Hans";
  if (root?.dataset.locale === "en") return "en";
  if (typeof window !== "undefined") {
    const urlParam = new URLSearchParams(window.location.search).get("lang");
    if (urlParam?.toLowerCase().startsWith("zh")) return "zh-Hans";
    if (urlParam?.toLowerCase().startsWith("en")) return "en";
    const stored = window.localStorage.getItem("liveclassroom_locale");
    if (stored === "zh-Hans" || stored === "zh") return "zh-Hans";
    if (stored === "en") return "en";
    const docLang = document.documentElement.lang;
    if (docLang && docLang.toLowerCase().startsWith("zh")) return "zh-Hans";
    if (docLang && docLang.toLowerCase().startsWith("en")) return "en";
  }
  return "en";
}

export function setStoredLocale(locale: Locale): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem("liveclassroom_locale", locale);
    document.documentElement.lang = locale === "zh-Hans" ? "zh-CN" : "en";
  }
}

export function t(key: TranslationKey, locale?: Locale): string {
  const activeLocale = locale ?? getLocale();
  return (translations[activeLocale] as Record<string, string>)[key] ?? translations.en[key] ?? String(key);
}

export function mountLanguageSwitcher(
  root: HTMLElement,
  onLocaleChange?: (locale: Locale) => void,
): HTMLElement {
  let switchBtn = root.querySelector<HTMLButtonElement>(".lc-lang-switch");
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
  switchBtn.innerHTML = currentLocale === "zh-Hans"
    ? '<span class="lc-lang-opt">EN</span> / <span class="lc-lang-opt lc-lang-curr">中文</span>'
    : '<span class="lc-lang-opt lc-lang-curr">EN</span> / <span class="lc-lang-opt">中文</span>';

  if (switchBtn.dataset.liveclassroomBound !== "true") {
    switchBtn.dataset.liveclassroomBound = "true";
    switchBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const current = getLocale(root);
      const nextLocale: Locale = current === "zh-Hans" ? "en" : "zh-Hans";
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
