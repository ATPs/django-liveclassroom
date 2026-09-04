import { deleteJson, getJson, postJson, putJson } from "./protocol.js";
import { getLocale, mountLanguageSwitcher, t, type Locale } from "./locales.js";
import { mountAiChat } from "./ai_chat.js";
import { mountFilePicker } from "./file_picker.js";

export type FlowSummary = {
  id: number;
  title: string;
  slug?: string;
  description?: string;
  course_id?: number | null;
  steps_count?: number;
  created_at?: string;
  updated_at?: string;
};

export type FlowStep = {
  id: number;
  position: number;
  kind: string;
  title: string;
  content?: Record<string, unknown> | null;
  activity_definition_id?: number | null;
  activity_definition?: {
    id: number;
    title: string;
    type_key: string;
    schema_version?: number;
    status?: string;
    definition: Record<string, unknown>;
  } | null;
  created_at?: string;
  updated_at?: string;
};

export type FlowDetail = FlowSummary & {
  steps: FlowStep[];
};

export type ActivityTypeInfo = {
  type_key: string;
  labelKey:
    | "singleChoice"
    | "multipleChoice"
    | "trueFalse"
    | "poll"
    | "shortText"
    | "numeric"
    | "rating"
    | "ranking"
    | "wordCloud"
    | "timer"
    | "markdownContent"
    | "mediaContent";
};

const ACTIVITY_TYPES: ActivityTypeInfo[] = [
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
  { type_key: "liveclassroom.media", labelKey: "mediaContent" },
];

export function mountBuilder(container: HTMLElement): void {
  const locale: Locale = getLocale(container);
  const rootDataset = container.dataset;
  const flowsUrl = new URL(rootDataset.apiV1Url ?? "/api/v1/flows/", window.location.href);
  const apiRoot = new URL("../", flowsUrl);
  const apiUrl = (path: string): string => new URL(path.replace(/^\/+/, ""), apiRoot).toString();

  // Session ID can come from dataset or URL query param
  let sessionId: number | null = null;
  if (rootDataset.sessionId) {
    sessionId = parseInt(rootDataset.sessionId, 10) || null;
  }
  if (!sessionId && typeof window !== "undefined") {
    const param = new URLSearchParams(window.location.search).get("session_id");
    if (param) sessionId = parseInt(param, 10) || null;
  }

  // Initial flow ID
  let activeFlowId: number | null = null;
  if (rootDataset.flowId) {
    activeFlowId = parseInt(rootDataset.flowId, 10) || null;
  }
  if (!activeFlowId && typeof window !== "undefined") {
    const param = new URLSearchParams(window.location.search).get("flow_id");
    if (param) activeFlowId = parseInt(param, 10) || null;
  }

  let flows: FlowSummary[] = [];
  let currentFlow: FlowDetail | null = null;
  const previewOpenSteps = new Set<number>();
  let isAiSidebarOpen = true;
  let isAddStepOpen = false;
  const allowServerPath = rootDataset.isSuperuser === "true";

  container.replaceChildren();
  const root = document.createElement("div");
  root.className = "lc-builder-root";
  container.append(root);

  mountLanguageSwitcher(container, (nextLocale) => {
    container.dataset.locale = nextLocale;
    mountBuilder(container);
  });

  // Layout Container: Main builder + Collapsible AI Sidebar
  const layout = document.createElement("div");
  layout.className = "lc-builder-layout";
  root.append(layout);

  const mainPane = document.createElement("div");
  mainPane.className = "lc-builder-main";
  layout.append(mainPane);

  const sidebarPane = document.createElement("div");
  sidebarPane.className = "lc-builder-sidebar";
  layout.append(sidebarPane);

  // Top Action Bar
  const topBar = document.createElement("div");
  topBar.className = "lc-builder-topbar";

  const titleGroup = document.createElement("div");
  titleGroup.className = "lc-builder-title-group";
  const pageTitle = document.createElement("h2");
  pageTitle.textContent = t("builderTitle", locale);
  titleGroup.append(pageTitle);

  // Flow Selector
  const flowSelectLabel = document.createElement("label");
  flowSelectLabel.className = "lc-builder-flow-select-label";
  flowSelectLabel.textContent = `${t("flows", locale)}: `;
  const flowSelect = document.createElement("select");
  flowSelect.className = "lc-builder-flow-select";
  flowSelect.addEventListener("change", () => {
    const id = parseInt(flowSelect.value, 10);
    if (!Number.isNaN(id) && id !== activeFlowId) {
      void loadFlow(id);
    }
  });
  flowSelectLabel.append(flowSelect);
  titleGroup.append(flowSelectLabel);
  topBar.append(titleGroup);

  // Action Buttons Group
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

  const fileBtn = document.createElement("button");
  fileBtn.type = "button";
  fileBtn.className = "lc-btn-sm lc-btn-outline";
  fileBtn.textContent = t("fileAdd", locale);
  fileBtn.addEventListener("click", () => {
    if (!currentFlow) return;
    const picker = document.createElement("div");
    picker.className = "lc-builder-step-form";
    const pickerHeading = document.createElement("h4");
    pickerHeading.textContent = t("fileAdd", locale);
    picker.append(pickerHeading);
    mountFilePicker(picker, {
      locale,
      endpoint: apiUrl(`flows/${currentFlow.id}/files/`),
      allowServerPath,
      onSuccess: () => void loadFlow(currentFlow!.id),
    });
    document.getElementById("lc-add-step-form-container")?.replaceChildren(picker);
  });
  actionsGroup.append(fileBtn);

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
  toggleAiBtn.textContent = `🤖 ${t("aiAssistant", locale)}`;
  toggleAiBtn.addEventListener("click", () => {
    isAiSidebarOpen = !isAiSidebarOpen;
    sidebarPane.style.display = isAiSidebarOpen ? "block" : "none";
  });
  actionsGroup.append(toggleAiBtn);

  topBar.append(actionsGroup);
  mainPane.append(topBar);

  // Status message banner
  const statusBanner = document.createElement("div");
  statusBanner.className = "lc-builder-status";
  statusBanner.style.display = "none";
  mainPane.append(statusBanner);

  function showStatus(msg: string, isError = false): void {
    statusBanner.textContent = msg;
    statusBanner.className = `lc-builder-status ${isError ? "lc-builder-status-error" : "lc-builder-status-success"}`;
    statusBanner.style.display = "block";
    setTimeout(() => {
      if (statusBanner.textContent === msg) {
        statusBanner.style.display = "none";
      }
    }, 4000);
  }

  // Flow Details Section
  const flowDetailSection = document.createElement("section");
  flowDetailSection.className = "lc-builder-flow-detail";
  mainPane.append(flowDetailSection);

  // Steps Section
  const stepsSection = document.createElement("section");
  stepsSection.className = "lc-builder-steps-section";
  mainPane.append(stepsSection);

  // Mount AI Chat into sidebar
  const aiChatWidget = mountAiChat(sidebarPane, {
    locale,
    apiRoot: apiRoot.toString(),
    getAttachment: () => {
      if (currentFlow) {
        return {
          source_type: "flow",
          source_id: currentFlow.id,
          title: currentFlow.title,
        };
      }
      return null;
    },
    onInsertDraft: (draftText: string) => {
      handleInsertDraft(draftText);
    },
  });

  // Flow Management
  async function loadFlows(): Promise<void> {
    try {
      const data = await getJson<{ flows: FlowSummary[] }>(apiUrl("flows/"));
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

      const targetId = activeFlowId && flows.some((f) => f.id === activeFlowId)
        ? activeFlowId
        : flows[0].id;
      await loadFlow(targetId);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to load flows", true);
    }
  }

  async function loadFlow(flowId: number): Promise<void> {
    try {
      activeFlowId = flowId;
      flowSelect.value = String(flowId);
      const data = await getJson<FlowDetail>(apiUrl(`flows/${flowId}/`));
      currentFlow = data;
      renderFlowDetails();
      renderSteps();
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to load flow details", true);
    }
  }

  async function handleCreateFlow(): Promise<void> {
    const title = window.prompt(t("newFlowPrompt", locale), "New Lesson Flow");
    if (!title || !title.trim()) return;
    try {
      const created = await postJson<FlowSummary>(apiUrl("flows/"), {
        title: title.trim(),
      });
      showStatus(t("flowUpdated", locale));
      await loadFlows();
      await loadFlow(created.id);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to create flow", true);
    }
  }

  async function handleDuplicateFlow(): Promise<void> {
    if (!currentFlow) return;
    const title = window.prompt(
      t("duplicateFlowPrompt", locale),
      `Copy of ${currentFlow.title}`,
    );
    if (title === null) return;
    try {
      const payload: Record<string, unknown> = {};
      if (title.trim()) payload.title = title.trim();
      const duplicated = await postJson<FlowDetail>(
        apiUrl(`flows/${currentFlow.id}/duplicate/`),
        payload,
      );
      showStatus(t("flowUpdated", locale));
      await loadFlows();
      await loadFlow(duplicated.id);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to duplicate flow", true);
    }
  }

  async function handleSaveSessionAsFlow(): Promise<void> {
    if (!sessionId) return;
    const title = window.prompt(t("saveAsFlowPrompt", locale), "Classroom Flow");
    if (!title || !title.trim()) return;
    try {
      const flow = await postJson<FlowDetail>(apiUrl(`sessions/${sessionId}/save-flow/`), {
        title: title.trim(),
      });
      showStatus(t("flowUpdated", locale));
      await loadFlows();
      await loadFlow(flow.id);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to save session as flow", true);
    }
  }

  // Render Flow Details (header, title, description)
  function renderFlowDetails(): void {
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

  // Render Flow Steps List
  function renderSteps(): void {
    stepsSection.replaceChildren();
    if (!currentFlow) return;

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

    // Step addition form container
    const addFormContainer = document.createElement("div");
    addFormContainer.id = "lc-add-step-form-container";
    stepsSection.append(addFormContainer);
    if (isAddStepOpen) renderAddStepForm();

    const list = document.createElement("div");
    list.className = "lc-builder-step-list";

    if (currentFlow.steps.length === 0) {
      const emptyP = document.createElement("p");
      emptyP.className = "lc-empty-notice";
      emptyP.textContent = t("noStepsYet", locale);
      list.append(emptyP);
    } else {
      currentFlow.steps.forEach((step, index) => {
        const card = createStepCard(step, index, currentFlow!.steps.length);
        list.append(card);
      });
    }

    stepsSection.append(list);
  }

  // Create Step Card
  function createStepCard(step: FlowStep, index: number, total: number): HTMLElement {
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
    const typeName = typeInfo ? t(typeInfo.labelKey, locale) : (step.kind === "markdown" ? t("markdownContent", locale) : typeKey);

    const typeBadge = document.createElement("span");
    typeBadge.className = "lc-step-type-badge";
    typeBadge.textContent = typeName;
    titleArea.append(typeBadge);

    const stepTitle = document.createElement("strong");
    stepTitle.className = "lc-step-name";
    stepTitle.textContent = step.title || step.activity_definition?.title || typeName;
    titleArea.append(stepTitle);

    cardHeader.append(titleArea);

    // Card Actions: Reorder, Preview, Launch, Delete
    const actionsArea = document.createElement("div");
    actionsArea.className = "lc-builder-step-actions";

    // Move Up
    const upBtn = document.createElement("button");
    upBtn.type = "button";
    upBtn.className = "lc-btn-icon";
    upBtn.title = t("moveUp", locale);
    upBtn.textContent = "↑";
    upBtn.disabled = index === 0;
    upBtn.addEventListener("click", () => void handleMoveStep(index, -1));
    actionsArea.append(upBtn);

    // Move Down
    const downBtn = document.createElement("button");
    downBtn.type = "button";
    downBtn.className = "lc-btn-icon";
    downBtn.title = t("moveDown", locale);
    downBtn.textContent = "↓";
    downBtn.disabled = index === total - 1;
    downBtn.addEventListener("click", () => void handleMoveStep(index, 1));
    actionsArea.append(downBtn);

    // Preview Toggle
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

    // Launch to live session (if sessionId provided)
    if (sessionId) {
      const launchBtn = document.createElement("button");
      launchBtn.type = "button";
      launchBtn.className = "lc-btn-sm lc-btn-secondary";
      launchBtn.textContent = `🚀 ${t("launchToClassroom", locale)}`;
      launchBtn.addEventListener("click", () => void handleLaunchStep(step));
      actionsArea.append(launchBtn);
    }

    // Delete step
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "lc-btn-sm lc-btn-danger";
    delBtn.textContent = t("removeStep", locale);
    delBtn.addEventListener("click", () => void handleDeleteStep(step));
    actionsArea.append(delBtn);

    cardHeader.append(actionsArea);
    card.append(cardHeader);

    // Preview Pane (if open)
    if (isPreviewOpen) {
      const previewBox = document.createElement("div");
      previewBox.className = "lc-builder-step-preview";
      renderStepLivePreview(previewBox, step);
      card.append(previewBox);
    }

    return card;
  }

  // Live Preview Renderer for Step
  function renderStepLivePreview(container: HTMLElement, step: FlowStep): void {
    container.replaceChildren();

    const previewHeader = document.createElement("div");
    previewHeader.className = "lc-preview-header";
    const headerTitle = document.createElement("small");
    headerTitle.textContent = `👁 ${t("previewHeading", locale)}`;
    previewHeader.append(headerTitle);
    container.append(previewHeader);

    const definition: Record<string, unknown> =
      step.activity_definition?.definition ??
      (step.content as Record<string, unknown> | undefined) ??
      {};

    const promptText = (definition.prompt as string) || (step.title as string) || "";
    const typeKey = step.activity_definition?.type_key || step.kind;

    // Prompt display
    if (promptText) {
      const promptEl = document.createElement("h4");
      promptEl.className = "lc-preview-prompt";
      promptEl.textContent = promptText;
      container.append(promptEl);
    }

    // Render by type
    if (
      typeKey === "liveclassroom.single_choice" ||
      typeKey === "liveclassroom.multiple_choice" ||
      typeKey === "liveclassroom.poll" ||
      typeKey === "liveclassroom.ranking"
    ) {
      const options = Array.isArray(definition.options) ? (definition.options as Array<Record<string, string>>) : [];
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

      container.append(list);

      // Correct answer & explanation feedback
      if (definition.answer) {
        const ans = document.createElement("p");
        ans.className = "lc-preview-answer";
        ans.textContent = `${t("correctAnswer", locale)}: ${Array.isArray(definition.answer) ? (definition.answer as string[]).join(", ") : String(definition.answer)}`;
        container.append(ans);
      }
      if (definition.explanation_markdown || definition.explanation) {
        const exp = document.createElement("p");
        exp.className = "lc-preview-explanation";
        exp.textContent = `${t("explanation", locale)}: ${String(definition.explanation_markdown || definition.explanation)}`;
        container.append(exp);
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
      container.append(btnRow);

      if (definition.answer) {
        const ans = document.createElement("p");
        ans.className = "lc-preview-answer";
        ans.textContent = `${t("correctAnswer", locale)}: ${Array.isArray(definition.answer) ? (definition.answer as string[]).join(", ") : String(definition.answer)}`;
        container.append(ans);
      }
    } else if (typeKey === "liveclassroom.short_text" || typeKey === "liveclassroom.word_cloud") {
      const input = document.createElement("input");
      input.type = "text";
      input.className = "lc-preview-input";
      input.placeholder = typeKey === "liveclassroom.word_cloud" ? "Enter a word…" : "Enter your answer…";
      input.disabled = true;
      container.append(input);
    } else if (typeKey === "liveclassroom.numeric") {
      const input = document.createElement("input");
      input.type = "number";
      input.className = "lc-preview-input";
      input.disabled = true;
      if (definition.minimum !== undefined) input.min = String(definition.minimum);
      if (definition.maximum !== undefined) input.max = String(definition.maximum);
      if (definition.step !== undefined) input.step = String(definition.step);
      container.append(input);
    } else if (typeKey === "liveclassroom.rating") {
      const starsRow = document.createElement("div");
      starsRow.className = "lc-preview-rating-row";
      const max = typeof definition.maximum === "number" ? definition.maximum : 5;
      for (let i = 1; i <= max; i++) {
        const star = document.createElement("button");
        star.type = "button";
        star.className = "lc-rating-btn";
        star.disabled = true;
        star.textContent = String(i);
        starsRow.append(star);
      }
      container.append(starsRow);
    } else if (typeKey === "liveclassroom.timer") {
      const timerBox = document.createElement("div");
      timerBox.className = "lc-preview-timer-box";
      const duration = definition.duration_seconds ?? 60;
      const label = (definition.label as string) || t("timer", locale);
      timerBox.textContent = `⏱ ${label}: ${duration}${t("seconds", locale)}`;
      container.append(timerBox);
    } else if (typeKey === "liveclassroom.markdown" || step.kind === "markdown") {
      const mdContent = (definition.markdown as string) || "";
      const mdBox = document.createElement("div");
      mdBox.className = "lc-preview-markdown";
      mdBox.textContent = mdContent;
      container.append(mdBox);
    } else if (typeKey === "liveclassroom.media") {
      const url = (definition.url as string) || "";
      const mediaType = (definition.media_type as string) || "image";
      const mediaBox = document.createElement("div");
      mediaBox.className = "lc-preview-media";

      if (mediaType === "image") {
        const img = document.createElement("img");
        img.src = url;
        img.alt = (definition.caption as string) || "Preview image";
        img.style.maxWidth = "100%";
        img.style.maxHeight = "16rem";
        mediaBox.append(img);
      } else {
        const link = document.createElement("a");
        link.href = url;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = `🔗 Open ${mediaType}: ${url}`;
        mediaBox.append(link);
      }

      if (definition.caption) {
        const cap = document.createElement("p");
        cap.className = "lc-preview-caption";
        cap.textContent = String(definition.caption);
        mediaBox.append(cap);
      }
      container.append(mediaBox);
    }
  }

  // Reorder Step (Up or Down)
  async function handleMoveStep(index: number, direction: -1 | 1): Promise<void> {
    if (!currentFlow) return;
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= currentFlow.steps.length) return;

    const newSteps = [...currentFlow.steps];
    const [moved] = newSteps.splice(index, 1);
    newSteps.splice(targetIndex, 0, moved);

    const stepIds = newSteps.map((s) => s.id);
    try {
      const res = await putJson<{ steps: FlowStep[] }>(
        apiUrl(`flows/${currentFlow.id}/steps/reorder/`),
        { step_ids: stepIds },
      );
      currentFlow.steps = res.steps;
      renderSteps();
      showStatus(t("stepsReordered", locale));
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to reorder steps", true);
    }
  }

  // Delete Step
  async function handleDeleteStep(step: FlowStep): Promise<void> {
    if (!currentFlow) return;
    if (!window.confirm(t("confirmDeleteStep", locale))) return;

    try {
      await deleteJson<{ deleted: boolean }>(
        apiUrl(`flows/${currentFlow.id}/steps/${step.id}/`),
      );
      currentFlow.steps = currentFlow.steps.filter((s) => s.id !== step.id);
      previewOpenSteps.delete(step.id);
      renderSteps();
      showStatus(t("stepDeleted", locale));
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to delete step", true);
    }
  }

  // Launch Step to Live Classroom Session
  async function handleLaunchStep(step: FlowStep): Promise<void> {
    if (!sessionId) return;
    try {
      await postJson(apiUrl(`sessions/${sessionId}/activities/`), {
        flow_step_id: step.id,
      });
      showStatus(t("launchedSuccess", locale));
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to launch activity", true);
    }
  }

  // Render Add Step Form
  function renderAddStepForm(initialDraft?: string): void {
    const containerEl = document.getElementById("lc-add-step-form-container");
    if (!containerEl) return;
    containerEl.replaceChildren();

    if (!isAddStepOpen) return;

    const formWrapper = document.createElement("div");
    formWrapper.className = "lc-builder-step-form";

    const formHeading = document.createElement("h4");
    formHeading.textContent = t("addStep", locale);
    formWrapper.append(formHeading);

    const errorBanner = document.createElement("div");
    errorBanner.className = "lc-form-error";
    errorBanner.style.display = "none";
    formWrapper.append(errorBanner);

    // Title field
    const titleGroup = document.createElement("div");
    titleGroup.className = "lc-form-group";
    const titleLabel = document.createElement("label");
    titleLabel.textContent = `${t("flowTitle", locale)}: `;
    const titleInput = document.createElement("input");
    titleInput.type = "text";
    titleInput.className = "lc-input";
    titleInput.placeholder = "e.g. Mendel's First Experiment";
    titleGroup.append(titleLabel, titleInput);
    formWrapper.append(titleGroup);

    // Type Selector
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

    // Dynamic fields container
    const dynamicFields = document.createElement("div");
    dynamicFields.className = "lc-dynamic-fields";
    formWrapper.append(dynamicFields);

    function renderDynamicInputs(): void {
      dynamicFields.replaceChildren();
      const selectedType = typeSelect.value;

      if (
        selectedType === "liveclassroom.single_choice" ||
        selectedType === "liveclassroom.multiple_choice" ||
        selectedType === "liveclassroom.poll" ||
        selectedType === "liveclassroom.ranking"
      ) {
        // Prompt
        const pGroup = document.createElement("div");
        pGroup.className = "lc-form-group";
        const pLabel = document.createElement("label");
        pLabel.textContent = `${t("promptLabel", locale)}: `;
        const pInput = document.createElement("textarea");
        pInput.className = "lc-textarea";
        pInput.id = "lc-field-prompt";
        pInput.rows = 2;
        if (initialDraft) pInput.value = initialDraft;
        pGroup.append(pLabel, pInput);
        dynamicFields.append(pGroup);

        // Options
        const optGroup = document.createElement("div");
        optGroup.className = "lc-form-group";
        const optLabel = document.createElement("label");
        optLabel.textContent = `${t("optionsLabel", locale)}: `;
        const optInput = document.createElement("textarea");
        optInput.className = "lc-textarea";
        optInput.id = "lc-field-options";
        optInput.rows = 4;
        optInput.placeholder = "Choice 1\nChoice 2\nChoice 3\nChoice 4";
        optGroup.append(optLabel, optInput);
        dynamicFields.append(optGroup);

        // Correct Answer (if single or multiple choice)
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

        // Explanation
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
        if (initialDraft) pInput.value = initialDraft;
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
      } else if (
        selectedType === "liveclassroom.short_text" ||
        selectedType === "liveclassroom.word_cloud"
      ) {
        const pGroup = document.createElement("div");
        pGroup.className = "lc-form-group";
        const pLabel = document.createElement("label");
        pLabel.textContent = `${t("promptLabel", locale)}: `;
        const pInput = document.createElement("textarea");
        pInput.className = "lc-textarea";
        pInput.id = "lc-field-prompt";
        pInput.rows = 2;
        if (initialDraft) pInput.value = initialDraft;
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
        if (initialDraft) pInput.value = initialDraft;
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
        if (selectedType === "liveclassroom.rating") minInput.value = "1";
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
        if (selectedType === "liveclassroom.rating") maxInput.value = "5";
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
        if (initialDraft) mdInput.value = initialDraft;
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

    // Form button row
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

  // Handle Save Step with Inline Validation
  async function handleSaveStep(
    errorBanner: HTMLElement,
    titleInput: HTMLInputElement,
    typeSelect: HTMLSelectElement,
  ): Promise<void> {
    if (!currentFlow) return;
    errorBanner.style.display = "none";
    errorBanner.textContent = "";

    const selectedType = typeSelect.value;
    const titleVal = titleInput.value.trim();

    const promptEl = document.getElementById("lc-field-prompt") as HTMLTextAreaElement | null;
    const promptVal = promptEl?.value.trim() ?? "";

    // Validation checks
    if (
      selectedType === "liveclassroom.single_choice" ||
      selectedType === "liveclassroom.multiple_choice" ||
      selectedType === "liveclassroom.poll" ||
      selectedType === "liveclassroom.ranking"
    ) {
      if (!promptVal && !titleVal) {
        errorBanner.textContent = t("validationError", locale);
        errorBanner.style.display = "block";
        return;
      }
      const optEl = document.getElementById("lc-field-options") as HTMLTextAreaElement | null;
      const lines = (optEl?.value || "")
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean);
      if (lines.length < 2) {
        errorBanner.textContent = "Please provide at least two options.";
        errorBanner.style.display = "block";
        return;
      }

      const options = lines.map((text, idx) => {
        const id = String.fromCharCode(65 + idx);
        // Strip leading "A. " or "A: " if already present
        const cleaned = text.replace(/^[A-Z][.:]\s*/, "");
        return { id, text: cleaned || text };
      });

      const definition: Record<string, unknown> = {
        prompt: promptVal || titleVal,
        options,
      };

      const ansEl = document.getElementById("lc-field-answer") as HTMLInputElement | null;
      if (ansEl && ansEl.value.trim()) {
        const rawAns = ansEl.value
          .split(/[, ]+/)
          .map((s) => s.trim().toUpperCase())
          .filter(Boolean);
        definition.answer = selectedType === "liveclassroom.single_choice" ? [rawAns[0]] : rawAns;
      }

      const expEl = document.getElementById("lc-field-explanation") as HTMLTextAreaElement | null;
      if (expEl && expEl.value.trim()) {
        definition.explanation_markdown = expEl.value.trim();
      }

      await submitStepPayload({
        kind: "activity",
        title: titleVal || promptVal,
        activity_definition: {
          title: titleVal || promptVal,
          type_key: selectedType,
          definition,
        },
      });
    } else if (selectedType === "liveclassroom.true_false") {
      if (!promptVal && !titleVal) {
        errorBanner.textContent = t("validationError", locale);
        errorBanner.style.display = "block";
        return;
      }
      const ansSel = document.getElementById("lc-field-answer") as HTMLSelectElement | null;
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
              { id: "false", text: "False" },
            ],
            answer: [ansVal],
          },
        },
      });
    } else if (
      selectedType === "liveclassroom.short_text" ||
      selectedType === "liveclassroom.word_cloud"
    ) {
      if (!promptVal && !titleVal) {
        errorBanner.textContent = t("validationError", locale);
        errorBanner.style.display = "block";
        return;
      }
      const definition: Record<string, unknown> = { prompt: promptVal || titleVal };
      if (selectedType === "liveclassroom.word_cloud") {
        const swEl = document.getElementById("lc-field-stopwords") as HTMLInputElement | null;
        if (swEl && swEl.value.trim()) {
          definition.stop_words = swEl.value
            .split(/[, ]+/)
            .map((s) => s.trim())
            .filter(Boolean);
        }
      }

      await submitStepPayload({
        kind: "activity",
        title: titleVal || promptVal,
        activity_definition: {
          title: titleVal || promptVal,
          type_key: selectedType,
          definition,
        },
      });
    } else if (selectedType === "liveclassroom.numeric" || selectedType === "liveclassroom.rating") {
      if (!promptVal && !titleVal) {
        errorBanner.textContent = t("validationError", locale);
        errorBanner.style.display = "block";
        return;
      }
      const definition: Record<string, unknown> = { prompt: promptVal || titleVal };
      const minEl = document.getElementById("lc-field-min") as HTMLInputElement | null;
      const maxEl = document.getElementById("lc-field-max") as HTMLInputElement | null;
      if (minEl && minEl.value) definition.minimum = parseFloat(minEl.value);
      if (maxEl && maxEl.value) definition.maximum = parseFloat(maxEl.value);

      await submitStepPayload({
        kind: "activity",
        title: titleVal || promptVal,
        activity_definition: {
          title: titleVal || promptVal,
          type_key: selectedType,
          definition,
        },
      });
    } else if (selectedType === "liveclassroom.timer") {
      const durEl = document.getElementById("lc-field-duration") as HTMLInputElement | null;
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
            label: titleVal || "Timer",
          },
        },
      });
    } else if (selectedType === "liveclassroom.markdown") {
      const mdEl = document.getElementById("lc-field-markdown") as HTMLTextAreaElement | null;
      const mdVal = mdEl?.value.trim() ?? "";
      if (!mdVal) {
        errorBanner.textContent = "Markdown content is required.";
        errorBanner.style.display = "block";
        return;
      }

      await submitStepPayload({
        kind: "markdown",
        title: titleVal || "Lecture Note",
        content: { markdown: mdVal },
      });
    } else if (selectedType === "liveclassroom.media") {
      const urlEl = document.getElementById("lc-field-url") as HTMLInputElement | null;
      const urlVal = urlEl?.value.trim() ?? "";
      if (!urlVal) {
        errorBanner.textContent = "Media URL is required.";
        errorBanner.style.display = "block";
        return;
      }
      const mtEl = document.getElementById("lc-field-media-type") as HTMLSelectElement | null;
      const capEl = document.getElementById("lc-field-caption") as HTMLInputElement | null;

      await submitStepPayload({
        kind: "activity",
        title: titleVal || "Media Presentation",
        activity_definition: {
          title: titleVal || "Media Presentation",
          type_key: selectedType,
          definition: {
            url: urlVal,
            media_type: mtEl?.value || "image",
            caption: capEl?.value.trim() || "",
          },
        },
      });
    }
  }

  // Submit step to backend
  async function submitStepPayload(payload: Record<string, unknown>): Promise<void> {
    if (!currentFlow) return;
    try {
      await postJson<FlowStep>(apiUrl(`flows/${currentFlow.id}/steps/`), payload);
      isAddStepOpen = false;
      showStatus(t("stepAdded", locale));
      await loadFlow(currentFlow.id);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : "Failed to add step", true);
    }
  }

  // Insert AI Draft into Builder
  function handleInsertDraft(draftText: string): void {
    isAddStepOpen = true;
    renderAddStepForm(draftText);
    const formEl = document.getElementById("lc-add-step-form-container");
    if (formEl) formEl.scrollIntoView({ behavior: "smooth" });
    showStatus("AI draft inserted into step editor. Review and save.");
  }

  // Import Flow Modal
  function showImportModal(): void {
    const existingModal = document.getElementById("lc-import-modal");
    if (existingModal) existingModal.remove();

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

    // Format selection
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

    // Textarea
    const textGroup = document.createElement("div");
    textGroup.className = "lc-form-group";
    const textInput = document.createElement("textarea");
    textInput.className = "lc-textarea";
    textInput.rows = 8;
    textInput.placeholder = t("importPlaceholder", locale);
    textGroup.append(textInput);
    modal.append(textGroup);

    // Modal action buttons
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
        const body: Record<string, unknown> = { source };
        if (fmtSelect.value) body.format = fmtSelect.value;
        const imported = await postJson<FlowDetail>(apiUrl("flows/import/"), body);
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

  // Initialize
  void loadFlows();
}
