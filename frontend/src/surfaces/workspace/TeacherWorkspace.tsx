import * as React from "react";
import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { deleteJson, getJson, patchJson, postJson } from "../../protocol.js";
import { getLocale, type Locale } from "../../locales.js";
import { LanguageSwitcher, LocaleProvider, useLocale } from "../../i18n.js";

type CourseDefaults = {
  access_mode?: string;
  admission_mode?: string;
  chat_enabled?: boolean;
  [key: string]: unknown;
};

type CourseSummary = {
  id: number;
  title: string;
  description?: string;
  defaults?: CourseDefaults;
  owner_id?: number;
  can_manage?: boolean;
};

type CourseMember = { id: number; username: string; role: string };

type CourseDetail = CourseSummary & {
  members: CourseMember[];
  lesson_ids: number[];
};

type TeachingCourseSummary = {
  id: number;
  title: string;
  description: string;
  owner_id: number;
};
type TeachingClassSummary = { id: number; title: string };
type TeachingCourseDetail = TeachingCourseSummary & { classes: TeachingClassSummary[] };
type TeachingCoursesPayload = { teaching_courses: TeachingCourseSummary[] };

type SessionSummary = {
  id: number;
  title: string;
  status: string;
  demo?: boolean;
  archived?: boolean;
  course_id?: number | null;
  flow_id?: number | null;
  source_session_id?: number | null;
  capabilities?: string[];
  console_url: string;
  student_view_url?: string;
  join_code?: string;
  can_delete?: boolean;
};

type FlowSummary = {
  id: number;
  title: string;
  description?: string;
  demo?: boolean;
  course_id?: number | null;
  steps_count?: number;
  can_edit?: boolean;
  shared?: boolean;
  can_share?: boolean;
  course_ids?: number[];
};

type FlowPreviewStep = {
  id: number;
  position?: number;
  activity_definition?: {
    title?: string;
    type_key?: string;
    asset_url?: string | null;
    definition?: Record<string, unknown>;
  };
};

type FlowPreview = { title?: string; steps?: FlowPreviewStep[] };

type SessionCreateValues = {
  title: string;
  courseId: number | null;
  flowId: number | null;
  sourceSessionId: number | null;
  accessMode?: string;
  admissionMode?: string;
  chatEnabled?: boolean;
};

type WorkspacePayload = { courses: CourseSummary[]; sessions: SessionSummary[] };
type SharesPayload = { shares: Array<{ user_id: number; username: string }> };

type WorkspaceTextKey =
  | "workspace"
  | "lessons"
  | "sharedWithMe"
  | "classes"
  | "recentSessions"
  | "newInstant"
  | "startFromLesson"
  | "publicDemo"
  | "useDemo"
  | "reuseSession"
  | "edit"
  | "share"
  | "duplicate"
  | "duplicateTitle"
  | "duplicateAction"
  | "shared"
  | "steps"
  | "noLessons"
  | "noSharedLessons"
  | "noClasses"
  | "courses"
  | "createCourse"
  | "courseTitle"
  | "saveCourse"
  | "deleteCourse"
  | "deleteCourseConfirm"
  | "attachMove"
  | "detachClass"
  | "chooseManageableClass"
  | "groupedClasses"
  | "ungroupedClasses"
  | "noCourses"
  | "noGroupedClasses"
  | "noUngroupedClasses"
  | "noRecentSessions"
  | "status"
  | "class"
  | "sessions"
  | "createClass"
  | "classTitle"
  | "description"
  | "saveClass"
  | "defaults"
  | "accessMode"
  | "admissionMode"
  | "chatEnabled"
  | "guestAccess"
  | "authenticatedAccess"
  | "bothAccess"
  | "openAdmission"
  | "waitingRoom"
  | "rosterOnly"
  | "enabled"
  | "disabled"
  | "members"
  | "username"
  | "role"
  | "addMember"
  | "remove"
  | "delete"
  | "deleteConfirm"
  | "endBeforeDelete"
  | "teacherRole"
  | "assistantRole"
  | "studentRole"
  | "noMembers"
  | "associateLessons"
  | "associate"
  | "dissociate"
  | "lessonSharing"
  | "noShares"
  | "shareWith"
  | "removeShare"
  | "title"
  | "chooseClass"
  | "noClass"
  | "instantHeading"
  | "fromLesson"
  | "fromSession"
  | "sessionOverrides"
  | "inheritDefaults"
  | "preview"
  | "hidePreview"
  | "previewPrompt"
  | "previewOptions"
  | "previewNoContent"
  | "activity"
  | "createSession"
  | "cancel"
  | "save"
  | "loading"
  | "saved"
  | "loadFailed"
  | "required"
  | "unknownError";

const workspaceCopy: Record<Locale, Record<WorkspaceTextKey, string>> = {
  en: {
    workspace: "Teacher workspace",
    lessons: "My lessons",
    sharedWithMe: "Shared with me",
    classes: "Classes",
    recentSessions: "Recent sessions",
    newInstant: "Instant classroom",
    startFromLesson: "Start from lesson",
    publicDemo: "Public demo",
    useDemo: "Use this demo",
    reuseSession: "Reuse session",
    edit: "Edit lesson",
    share: "Share",
    duplicate: "Duplicate",
    duplicateTitle: "New lesson title",
    duplicateAction: "Create duplicate",
    shared: "Shared",
    steps: "steps",
    noLessons: "No lessons yet.",
    noSharedLessons: "No lessons have been shared with you.",
    noClasses: "No classes yet.",
    courses: "Courses",
    createCourse: "Create course",
    courseTitle: "Course title",
    saveCourse: "Save course",
    deleteCourse: "Delete course",
    deleteCourseConfirm: "Delete \"{title}\"? Classes and their data will remain.",
    attachMove: "Attach or move class",
    detachClass: "Detach",
    chooseManageableClass: "Choose a class",
    groupedClasses: "Classes in this course",
    ungroupedClasses: "Ungrouped classes",
    noCourses: "No courses yet.",
    noGroupedClasses: "No classes in this course.",
    noUngroupedClasses: "All manageable classes are grouped.",
    noRecentSessions: "No recent sessions.",
    status: "Status",
    class: "Class",
    sessions: "sessions",
    createClass: "Create class",
    classTitle: "Class title",
    description: "Description",
    saveClass: "Save class",
    defaults: "Classroom defaults",
    accessMode: "Student access",
    admissionMode: "Admission",
    chatEnabled: "Class chat",
    guestAccess: "Guest link",
    authenticatedAccess: "Authenticated users",
    bothAccess: "Guest and authenticated",
    openAdmission: "Open entry",
    waitingRoom: "Waiting room",
    rosterOnly: "Roster only",
    enabled: "Enabled",
    disabled: "Disabled",
    members: "Members",
    username: "Username",
    role: "Role",
    addMember: "Add member",
    remove: "Remove",
    delete: "Delete",
    deleteConfirm: "Delete \"{title}\" permanently? Its attendance, answers, chat, and classroom history will be removed. Your reusable lesson will remain.",
    endBeforeDelete: "End this classroom before deleting it.",
    teacherRole: "Teacher",
    assistantRole: "Assistant",
    studentRole: "Student",
    noMembers: "No members yet.",
    associateLessons: "Class lessons",
    associate: "Add to class",
    dissociate: "Remove from class",
    lessonSharing: "Lesson sharing",
    noShares: "No one has access yet.",
    shareWith: "Share with username",
    removeShare: "Remove access",
    title: "Title",
    chooseClass: "Class for this classroom",
    noClass: "No class",
    instantHeading: "New classroom",
    fromLesson: "Lesson",
    fromSession: "Reuse",
    sessionOverrides: "Session overrides",
    inheritDefaults: "Inherit class/server defaults",
    preview: "Preview",
    hidePreview: "Hide preview",
    previewPrompt: "Prompt",
    previewOptions: "Options",
    previewNoContent: "This lesson has no previewable content.",
    activity: "Activity",
    createSession: "Create classroom",
    cancel: "Cancel",
    save: "Save",
    loading: "Loading…",
    saved: "Saved.",
    loadFailed: "Unable to load workspace.",
    required: "A title is required.",
    unknownError: "Something went wrong.",
  },
  "zh-Hans": {
    workspace: "教师工作台",
    lessons: "我的教案",
    sharedWithMe: "分享给我",
    classes: "班级",
    recentSessions: "最近课堂",
    newInstant: "即时课堂",
    startFromLesson: "从教案开始",
    publicDemo: "公开示例",
    useDemo: "使用此示例",
    reuseSession: "复用课堂",
    edit: "编辑教案",
    share: "分享",
    duplicate: "复制",
    duplicateTitle: "新教案名称",
    duplicateAction: "创建副本",
    shared: "已分享",
    steps: "步骤",
    noLessons: "还没有教案。",
    noSharedLessons: "还没有分享给你的教案。",
    noClasses: "还没有班级。",
    courses: "课程",
    createCourse: "创建课程",
    courseTitle: "课程名称",
    saveCourse: "保存课程",
    deleteCourse: "删除课程",
    deleteCourseConfirm: "删除“{title}”吗？班级及其数据会保留。",
    attachMove: "加入或移动班级",
    detachClass: "移出课程",
    chooseManageableClass: "选择班级",
    groupedClasses: "课程中的班级",
    ungroupedClasses: "未分组班级",
    noCourses: "还没有课程。",
    noGroupedClasses: "此课程还没有班级。",
    noUngroupedClasses: "所有可管理班级都已分组。",
    noRecentSessions: "还没有最近课堂。",
    status: "状态",
    class: "班级",
    sessions: "课堂",
    createClass: "创建班级",
    classTitle: "班级名称",
    description: "描述",
    saveClass: "保存班级",
    defaults: "课堂默认设置",
    accessMode: "学生访问",
    admissionMode: "准入方式",
    chatEnabled: "课堂聊天",
    guestAccess: "访客链接",
    authenticatedAccess: "登录用户",
    bothAccess: "访客和登录用户",
    openAdmission: "开放进入",
    waitingRoom: "等待室",
    rosterOnly: "仅名册",
    enabled: "开启",
    disabled: "关闭",
    members: "成员",
    username: "用户名",
    role: "角色",
    addMember: "添加成员",
    remove: "移除",
    delete: "删除",
    deleteConfirm: "永久删除“{title}”吗？其出席、答案、聊天和课堂记录将被移除；教案会保留。",
    endBeforeDelete: "请先结束此课堂，再删除。",
    teacherRole: "教师",
    assistantRole: "助教",
    studentRole: "学生",
    noMembers: "还没有成员。",
    associateLessons: "班级教案",
    associate: "加入班级",
    dissociate: "移出班级",
    lessonSharing: "教案分享",
    noShares: "还没有其他人获得访问权限。",
    shareWith: "分享给用户名",
    removeShare: "移除访问权限",
    title: "标题",
    chooseClass: "此课堂所属班级",
    noClass: "不选择班级",
    instantHeading: "新建课堂",
    fromLesson: "教案",
    fromSession: "复用",
    sessionOverrides: "课堂覆盖设置",
    inheritDefaults: "继承班级或服务器默认设置",
    preview: "预览",
    hidePreview: "隐藏预览",
    previewPrompt: "题干",
    previewOptions: "选项",
    previewNoContent: "此教案没有可预览的内容。",
    activity: "活动",
    createSession: "创建课堂",
    cancel: "取消",
    save: "保存",
    loading: "加载中…",
    saved: "已保存。",
    loadFailed: "无法加载工作台。",
    required: "请输入标题。",
    unknownError: "操作失败。",
  },
};

function useWorkspaceText(): (key: WorkspaceTextKey) => string {
  const locale = useLocale();
  return useCallback((key: WorkspaceTextKey) => workspaceCopy[locale][key], [locale]);
}

function endpoint(apiRoot: string, tail: string): string {
  const base = new URL(apiRoot, window.location.href);
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  return new URL(tail.replace(/^\/+/, ""), base).toString();
}

function normalizeApiRoot(value: string): string {
  const base = new URL(value, window.location.href);
  base.pathname = base.pathname.replace(/workspace\/?$/, "");
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  base.search = "";
  base.hash = "";
  return base.toString();
}

function operationKey(operation: string): string {
  const nonce = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `workspace-${operation}-${nonce}`;
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

type RunAction = (operation: string, action: (key: string) => Promise<void>) => Promise<void>;

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function textValue(value: unknown): string {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean"
    ? String(value)
    : "";
}

function previewDefinition(activity: FlowPreviewStep["activity_definition"]): Record<string, unknown> {
  const definition = activity?.definition ?? {};
  const content = recordValue(definition.content);
  const question = recordValue(definition.question);
  return Object.keys(content).length ? content : Object.keys(question).length ? question : definition;
}

function previewPrompt(activity: FlowPreviewStep["activity_definition"]): string {
  const definition = activity ? previewDefinition(activity) : {};
  return textValue(definition.prompt)
    || textValue(definition.stem_markdown)
    || textValue(definition.markdown);
}

function previewOptions(activity: FlowPreviewStep["activity_definition"]): string[] {
  const definition = activity ? previewDefinition(activity) : {};
  const data = recordValue(definition.data);
  const rawOptions = Array.isArray(definition.options)
    ? definition.options
    : Array.isArray(definition.choices)
      ? definition.choices
      : Array.isArray(data.options)
        ? data.options
        : Array.isArray(data.choices)
          ? data.choices
          : [];

  return rawOptions.flatMap((option, index) => {
    if (typeof option === "string") {
      return option.trim() ? [`${String.fromCharCode(65 + index)}. ${option}`] : [];
    }
    const value = recordValue(option);
    const label = textValue(value.text) || textValue(value.label) || textValue(value.value);
    if (!label) return [];
    const id = textValue(value.id);
    return [`${id ? `${id}. ` : ""}${label}`];
  });
}

function SessionComposer({
  seed,
  courses,
  busy,
  onCancel,
  onCreate,
}: {
  seed: { flowId?: number | null; sourceSessionId?: number | null; label: string };
  courses: CourseSummary[];
  busy: boolean;
  onCancel: () => void;
  onCreate: (values: SessionCreateValues) => Promise<void>;
}) {
  const t = useWorkspaceText();
  const [title, setTitle] = useState("");
  const [courseId, setCourseId] = useState("");
  const [accessMode, setAccessMode] = useState("");
  const [admissionMode, setAdmissionMode] = useState("");
  const [chatEnabled, setChatEnabled] = useState("");

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) return;
    void onCreate({
      title: trimmed,
      courseId: courseId ? Number(courseId) : null,
      flowId: seed.flowId ?? null,
      sourceSessionId: seed.sourceSessionId ?? null,
      accessMode: accessMode || undefined,
      admissionMode: admissionMode || undefined,
      chatEnabled: chatEnabled === "" ? undefined : chatEnabled === "true",
    });
  };

  return (
    <section className="lc-workspace-composer" aria-labelledby="workspace-composer-title">
      <h2 id="workspace-composer-title">{t("instantHeading")}</h2>
      <p>{seed.label}</p>
      <form className="lc-form" onSubmit={submit}>
        <div className="lc-form-group">
          <label htmlFor="workspace-session-title">{t("title")}</label>
          <input
            id="workspace-session-title"
            className="lc-input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            maxLength={200}
            autoFocus
          />
        </div>
        <div className="lc-form-group">
          <label htmlFor="workspace-session-class">{t("chooseClass")}</label>
          <select
            id="workspace-session-class"
            className="lc-select"
            value={courseId}
            onChange={(event) => setCourseId(event.target.value)}
          >
            <option value="">{t("noClass")}</option>
            {courses.map((course) => <option key={course.id} value={String(course.id)}>{course.title}</option>)}
          </select>
        </div>
        <fieldset className="lc-form-group">
          <legend>{t("sessionOverrides")}</legend>
          <label htmlFor="workspace-session-access">{t("accessMode")}</label>
          <select
            id="workspace-session-access"
            className="lc-select"
            value={accessMode}
            onChange={(event) => setAccessMode(event.target.value)}
          >
            <option value="">{t("inheritDefaults")}</option>
            <option value="guest">{t("guestAccess")}</option>
            <option value="authenticated">{t("authenticatedAccess")}</option>
            <option value="both">{t("bothAccess")}</option>
          </select>
          <label htmlFor="workspace-session-admission">{t("admissionMode")}</label>
          <select
            id="workspace-session-admission"
            className="lc-select"
            value={admissionMode}
            onChange={(event) => setAdmissionMode(event.target.value)}
          >
            <option value="">{t("inheritDefaults")}</option>
            <option value="open">{t("openAdmission")}</option>
            <option value="waiting_room">{t("waitingRoom")}</option>
            <option value="roster">{t("rosterOnly")}</option>
          </select>
          <label htmlFor="workspace-session-chat">{t("chatEnabled")}</label>
          <select
            id="workspace-session-chat"
            className="lc-select"
            value={chatEnabled}
            onChange={(event) => setChatEnabled(event.target.value)}
          >
            <option value="">{t("inheritDefaults")}</option>
            <option value="true">{t("enabled")}</option>
            <option value="false">{t("disabled")}</option>
          </select>
        </fieldset>
        <div className="lc-form-btn-row">
          <button type="submit" className="lc-btn-sm lc-btn-primary" disabled={busy}>{t("createSession")}</button>
          <button type="button" className="lc-btn-sm lc-btn-outline" onClick={onCancel} disabled={busy}>{t("cancel")}</button>
        </div>
      </form>
    </section>
  );
}

function LessonCard({
  flow,
  apiRoot,
  builderUrl,
  run,
  busy,
  onStart,
  onRefresh,
}: {
  flow: FlowSummary;
  apiRoot: string;
  builderUrl: string;
  run: RunAction;
  busy: string | null;
  onStart: (flowId: number, demo?: boolean) => void;
  onRefresh: () => Promise<void>;
}) {
  const t = useWorkspaceText();
  const [duplicateTitle, setDuplicateTitle] = useState("");
  const [shareOpen, setShareOpen] = useState(false);
  const [shareUsername, setShareUsername] = useState("");
  const [shares, setShares] = useState<Array<{ user_id: number; username: string }>>([]);
  const [shareBusy, setShareBusy] = useState(false);
  const [shareError, setShareError] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [preview, setPreview] = useState<FlowPreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState("");

  const builderLink = (() => {
    const url = new URL(builderUrl, window.location.href);
    url.searchParams.set("flow_id", String(flow.id));
    return url.toString();
  })();

  const loadShares = useCallback(async () => {
    setShareBusy(true);
    setShareError("");
    try {
      const data = await getJson<SharesPayload>(endpoint(apiRoot, `flows/${flow.id}/shares/`));
      setShares(data.shares ?? []);
    } catch (error) {
      setShareError(errorText(error, t("unknownError")));
    } finally {
      setShareBusy(false);
    }
  }, [apiRoot, flow.id, t]);

  const toggleShares = () => {
    const next = !shareOpen;
    setShareOpen(next);
    if (next) void loadShares();
  };

  const loadPreview = useCallback(async () => {
    setPreviewBusy(true);
    setPreviewError("");
    try {
      setPreview(await getJson<FlowPreview>(endpoint(apiRoot, `flows/${flow.id}/`)));
    } catch (error) {
      setPreviewError(errorText(error, t("unknownError")));
    } finally {
      setPreviewBusy(false);
    }
  }, [apiRoot, flow.id, t]);

  const togglePreview = () => {
    const next = !previewOpen;
    setPreviewOpen(next);
    if (next) void loadPreview();
  };

  const share = (username: string, remove = false) => {
    void run(`flow-share-${flow.id}`, async (key) => {
      await postJson(endpoint(apiRoot, `flows/${flow.id}/shares/`), { username, remove }, key);
      await loadShares();
      setShareUsername("");
    });
  };

  const duplicate = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const title = duplicateTitle.trim();
    if (!title) return;
    void run(`flow-duplicate-${flow.id}`, async (key) => {
      await postJson(endpoint(apiRoot, `flows/${flow.id}/duplicate/`), { title }, key);
      setDuplicateTitle("");
      await onRefresh();
    });
  };

  return (
    <article className="lc-card lc-workspace-item">
      <div className="lc-workspace-item-header">
        <div>
          <h3>{flow.title}</h3>
          {flow.description ? <p>{flow.description}</p> : null}
        </div>
        {flow.demo ? <span className="lc-badge">{t("publicDemo")}</span> : flow.shared ? <span className="lc-badge">{t("shared")}</span> : null}
      </div>
      <p className="lc-workspace-meta">{flow.steps_count ?? 0} {t("steps")}</p>
      <div className="lc-actions">
        <button type="button" className="lc-btn-sm lc-btn-primary" onClick={() => onStart(flow.id, flow.demo)} disabled={Boolean(busy)}>{flow.demo ? t("useDemo") : t("startFromLesson")}</button>
        {flow.can_edit ? <a className="lc-btn-sm lc-btn-outline" href={builderLink}>{t("edit")}</a> : null}
        <button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => setDuplicateTitle(flow.title)} disabled={Boolean(busy)}>{t("duplicate")}</button>
        {flow.shared ? <button type="button" className="lc-btn-sm lc-btn-outline" onClick={togglePreview} disabled={Boolean(busy) || previewBusy}>{previewOpen ? t("hidePreview") : t("preview")}</button> : null}
        {flow.can_share ? <button type="button" className="lc-btn-sm lc-btn-outline" onClick={toggleShares} disabled={Boolean(busy) || shareBusy}>{t("share")}</button> : null}
      </div>
      {duplicateTitle ? (
        <form className="lc-form" onSubmit={duplicate}>
          <div className="lc-form-group">
            <label htmlFor={`duplicate-title-${flow.id}`}>{t("duplicateTitle")}</label>
            <input id={`duplicate-title-${flow.id}`} className="lc-input" value={duplicateTitle} onChange={(event) => setDuplicateTitle(event.target.value)} required maxLength={200} />
          </div>
          <div className="lc-form-btn-row">
            <button type="submit" className="lc-btn-sm lc-btn-primary" disabled={Boolean(busy)}>{t("duplicateAction")}</button>
            <button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => setDuplicateTitle("")} disabled={Boolean(busy)}>{t("cancel")}</button>
          </div>
        </form>
      ) : null}
      {shareOpen ? (
        <section className="lc-workspace-share" aria-labelledby={`share-heading-${flow.id}`}>
          <h4 id={`share-heading-${flow.id}`}>{t("lessonSharing")}</h4>
          {shareError ? <p className="lc-form-error">{shareError}</p> : null}
          {shareBusy ? <p>{t("loading")}</p> : shares.length ? (
            <ul>
              {shares.map((shareItem) => (
                <li key={shareItem.user_id}>
                  {shareItem.username} <button type="button" className="lc-btn-sm lc-btn-subtle" onClick={() => share(shareItem.username, true)} disabled={Boolean(busy)}>{t("removeShare")}</button>
                </li>
              ))}
            </ul>
          ) : <p>{t("noShares")}</p>}
          <form className="lc-form" onSubmit={(event) => { event.preventDefault(); if (shareUsername.trim()) share(shareUsername.trim()); }}>
            <div className="lc-form-group">
              <label htmlFor={`share-username-${flow.id}`}>{t("shareWith")}</label>
              <input id={`share-username-${flow.id}`} className="lc-input" value={shareUsername} onChange={(event) => setShareUsername(event.target.value)} required />
            </div>
            <button type="submit" className="lc-btn-sm lc-btn-primary" disabled={Boolean(busy) || shareBusy}>{t("share")}</button>
          </form>
        </section>
      ) : null}
      {previewOpen ? (
        <section className="lc-workspace-preview" aria-labelledby={`preview-heading-${flow.id}`}>
          <h4 id={`preview-heading-${flow.id}`}>{t("preview")}: {preview?.title ?? flow.title}</h4>
          {previewBusy ? <p>{t("loading")}</p> : previewError ? <p className="lc-form-error">{previewError}</p> : preview?.steps?.length ? (
            <ol>
              {preview.steps.map((step, index) => {
                const activity = step.activity_definition;
                const title = textValue(activity?.title) || `${t("activity")} ${index + 1}`;
                const prompt = previewPrompt(activity);
                const options = previewOptions(activity);
                return (
                  <li key={step.id}>
                    <h5>{title}</h5>
                    {activity?.asset_url ? <a href={activity.asset_url} target="_blank" rel="noopener noreferrer">{t("preview")}: {title}</a> : null}
                    {prompt ? <p><strong>{t("previewPrompt")}:</strong> {prompt}</p> : null}
                    {options.length ? (
                      <div>
                        <strong>{t("previewOptions")}:</strong>
                        <ul>{options.map((option, optionIndex) => <li key={`${optionIndex}-${option}`}>{option}</li>)}</ul>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          ) : <p>{t("previewNoContent")}</p>}
        </section>
      ) : null}
    </article>
  );
}

function CourseCard({
  course,
  flows,
  apiRoot,
  run,
  busy,
}: {
  course: CourseSummary;
  flows: FlowSummary[];
  apiRoot: string;
  run: RunAction;
  busy: string | null;
}) {
  const t = useWorkspaceText();
  const [detail, setDetail] = useState<CourseDetail | null>(null);
  const [detailBusy, setDetailBusy] = useState(true);
  const [detailError, setDetailError] = useState("");
  const [title, setTitle] = useState(course.title);
  const [description, setDescription] = useState(course.description ?? "");
  const [accessMode, setAccessMode] = useState(course.defaults?.access_mode ?? "guest");
  const [admissionMode, setAdmissionMode] = useState(course.defaults?.admission_mode ?? "open");
  const [chatEnabled, setChatEnabled] = useState(course.defaults?.chat_enabled === true);
  const [memberUsername, setMemberUsername] = useState("");
  const [memberRole, setMemberRole] = useState("student");
  const canManage = detail?.can_manage ?? course.can_manage === true;

  const loadDetail = useCallback(async () => {
    setDetailBusy(true);
    setDetailError("");
    try {
      const loaded = await getJson<CourseDetail>(endpoint(apiRoot, `courses/${course.id}/`));
      setDetail(loaded);
      setTitle(loaded.title);
      setDescription(loaded.description ?? "");
      setAccessMode(loaded.defaults?.access_mode ?? "guest");
      setAdmissionMode(loaded.defaults?.admission_mode ?? "open");
      setChatEnabled(loaded.defaults?.chat_enabled === true);
    } catch (error) {
      setDetailError(errorText(error, t("unknownError")));
    } finally {
      setDetailBusy(false);
    }
  }, [apiRoot, course.id, t]);

  useEffect(() => { void loadDetail(); }, [loadDetail]);

  const save = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canManage) return;
    void run(`course-save-${course.id}`, async (key) => {
      await postJson(endpoint(apiRoot, `courses/${course.id}/`), {
        title: title.trim(),
        description,
        defaults: { access_mode: accessMode, admission_mode: admissionMode, chat_enabled: chatEnabled },
      }, key);
      await loadDetail();
    });
  };

  const member = (username: string, remove = false) => {
    if (!canManage) return;
    void run(`course-member-${course.id}`, async (key) => {
      await postJson(endpoint(apiRoot, `courses/${course.id}/members/`), { username, role: memberRole, remove }, key);
      setMemberUsername("");
      await loadDetail();
    });
  };

  const associate = (flowId: number, remove: boolean) => {
    void run(`course-lesson-${course.id}-${flowId}`, async (key) => {
      await postJson(endpoint(apiRoot, `courses/${course.id}/lessons/`), { flow_id: flowId, remove }, key);
      await loadDetail();
    });
  };

  return (
    <article className="lc-card lc-workspace-course">
      <h3>{course.title}</h3>
      {detailError ? <p className="lc-form-error">{detailError}</p> : null}
      {detailBusy && !detail ? <p>{t("loading")}</p> : null}
      <form className="lc-form" onSubmit={save}>
        <div className="lc-form-group">
          <label htmlFor={`course-title-${course.id}`}>{t("classTitle")}</label>
          <input id={`course-title-${course.id}`} className="lc-input" value={title} onChange={(event) => setTitle(event.target.value)} required maxLength={200} disabled={!canManage} />
        </div>
        <div className="lc-form-group">
          <label htmlFor={`course-description-${course.id}`}>{t("description")}</label>
          <textarea id={`course-description-${course.id}`} className="lc-textarea" value={description} onChange={(event) => setDescription(event.target.value)} rows={2} disabled={!canManage} />
        </div>
        <fieldset className="lc-form-group">
          <legend>{t("defaults")}</legend>
          <label htmlFor={`course-access-${course.id}`}>{t("accessMode")}</label>
          <select id={`course-access-${course.id}`} className="lc-select" value={accessMode} onChange={(event) => setAccessMode(event.target.value)} disabled={!canManage}>
            <option value="guest">{t("guestAccess")}</option>
            <option value="authenticated">{t("authenticatedAccess")}</option>
            <option value="both">{t("bothAccess")}</option>
          </select>
          <label htmlFor={`course-admission-${course.id}`}>{t("admissionMode")}</label>
          <select id={`course-admission-${course.id}`} className="lc-select" value={admissionMode} onChange={(event) => setAdmissionMode(event.target.value)} disabled={!canManage}>
            <option value="open">{t("openAdmission")}</option>
            <option value="waiting_room">{t("waitingRoom")}</option>
            <option value="roster">{t("rosterOnly")}</option>
          </select>
          <label htmlFor={`course-chat-${course.id}`}>{t("chatEnabled")}</label>
          <select id={`course-chat-${course.id}`} className="lc-select" value={chatEnabled ? "true" : "false"} onChange={(event) => setChatEnabled(event.target.value === "true")} disabled={!canManage}>
            <option value="true">{t("enabled")}</option>
            <option value="false">{t("disabled")}</option>
          </select>
        </fieldset>
        <button type="submit" className="lc-btn-sm lc-btn-primary" disabled={!canManage || Boolean(busy) || detailBusy}>{t("saveClass")}</button>
      </form>
      <section className="lc-workspace-course-section" aria-labelledby={`members-heading-${course.id}`}>
        <h4 id={`members-heading-${course.id}`}>{t("members")}</h4>
        {detail?.members.length ? (
          <ul>
            {detail.members.map((memberItem) => (
              <li key={memberItem.id}>
                  {memberItem.username} ({memberItem.role}) <button type="button" className="lc-btn-sm lc-btn-subtle" onClick={() => member(memberItem.username, true)} disabled={!canManage || Boolean(busy)}>{t("remove")}</button>
              </li>
            ))}
          </ul>
        ) : <p>{t("noMembers")}</p>}
        <form className="lc-form" onSubmit={(event) => { event.preventDefault(); if (memberUsername.trim()) member(memberUsername.trim()); }}>
          <div className="lc-form-row">
            <div className="lc-form-group">
              <label htmlFor={`member-username-${course.id}`}>{t("username")}</label>
              <input id={`member-username-${course.id}`} className="lc-input" value={memberUsername} onChange={(event) => setMemberUsername(event.target.value)} required disabled={!canManage} />
            </div>
            <div className="lc-form-group">
              <label htmlFor={`member-role-${course.id}`}>{t("role")}</label>
              <select id={`member-role-${course.id}`} className="lc-select" value={memberRole} onChange={(event) => setMemberRole(event.target.value)} disabled={!canManage}>
                <option value="teacher">{t("teacherRole")}</option>
                <option value="assistant">{t("assistantRole")}</option>
                <option value="student">{t("studentRole")}</option>
              </select>
            </div>
          </div>
          <button type="submit" className="lc-btn-sm lc-btn-primary" disabled={!canManage || Boolean(busy)}>{t("addMember")}</button>
        </form>
      </section>
      <section className="lc-workspace-course-section" aria-labelledby={`lessons-heading-${course.id}`}>
        <h4 id={`lessons-heading-${course.id}`}>{t("associateLessons")}</h4>
        {flows.length ? (
          <ul>
            {flows.map((flow) => {
              const associated = detail?.lesson_ids.includes(flow.id) ?? false;
              return (
                <li key={flow.id}>
                  {flow.title} <button type="button" className="lc-btn-sm lc-btn-subtle" onClick={() => associate(flow.id, associated)} disabled={Boolean(busy)}>{associated ? t("dissociate") : t("associate")}</button>
                </li>
              );
            })}
          </ul>
        ) : <p>{t("noLessons")}</p>}
      </section>
    </article>
  );
}

function TeachingCourseCard({
  teachingCourse,
  manageableClasses,
  apiRoot,
  run,
  busy,
  refresh,
}: {
  teachingCourse: TeachingCourseDetail;
  manageableClasses: CourseSummary[];
  apiRoot: string;
  run: RunAction;
  busy: string | null;
  refresh: () => Promise<void>;
}) {
  const t = useWorkspaceText();
  const [title, setTitle] = useState(teachingCourse.title);
  const [description, setDescription] = useState(teachingCourse.description);
  const [classId, setClassId] = useState("");

  useEffect(() => {
    setTitle(teachingCourse.title);
    setDescription(teachingCourse.description);
  }, [teachingCourse.description, teachingCourse.title]);

  const save = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!title.trim()) return;
    void run(`teaching-course-save-${teachingCourse.id}`, async (key) => {
      await patchJson(endpoint(apiRoot, `teaching-courses/${teachingCourse.id}/`), {
        title: title.trim(),
        description,
      }, key);
      await refresh();
    });
  };

  const remove = () => {
    if (!window.confirm(t("deleteCourseConfirm").replace("{title}", teachingCourse.title))) return;
    void run(`teaching-course-delete-${teachingCourse.id}`, async (key) => {
      await deleteJson(endpoint(apiRoot, `teaching-courses/${teachingCourse.id}/`), key);
      await refresh();
    });
  };

  const attach = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!classId) return;
    void run(`teaching-course-attach-${teachingCourse.id}-${classId}`, async (key) => {
      await postJson(endpoint(apiRoot, `teaching-courses/${teachingCourse.id}/classes/`), {
        class_id: Number(classId),
      }, key);
      setClassId("");
      await refresh();
    });
  };

  const detach = (item: TeachingClassSummary) => {
    void run(`teaching-course-detach-${teachingCourse.id}-${item.id}`, async (key) => {
      await deleteJson(endpoint(apiRoot, `teaching-courses/${teachingCourse.id}/classes/${item.id}/`), key);
      await refresh();
    });
  };

  return (
    <article className="lc-teaching-course">
      <h3>{teachingCourse.title}</h3>
      <form className="lc-form" onSubmit={save}>
        <div className="lc-form-row">
          <div className="lc-form-group">
            <label htmlFor={`teaching-course-title-${teachingCourse.id}`}>{t("courseTitle")}</label>
            <input id={`teaching-course-title-${teachingCourse.id}`} className="lc-input" value={title} onChange={(event) => setTitle(event.target.value)} required maxLength={200} />
          </div>
          <div className="lc-form-group">
            <label htmlFor={`teaching-course-description-${teachingCourse.id}`}>{t("description")}</label>
            <input id={`teaching-course-description-${teachingCourse.id}`} className="lc-input" value={description} onChange={(event) => setDescription(event.target.value)} />
          </div>
        </div>
        <div className="lc-actions">
          <button type="submit" className="lc-btn-sm lc-btn-primary" disabled={Boolean(busy)}>{t("saveCourse")}</button>
          <button type="button" className="lc-btn-sm lc-btn-danger" onClick={remove} disabled={Boolean(busy)}>{t("deleteCourse")}</button>
        </div>
      </form>
      <div className="lc-teaching-course-classes">
        <h4>{t("groupedClasses")}</h4>
        {teachingCourse.classes.length ? (
          <ul className="lc-compact-list">
            {teachingCourse.classes.map((item) => (
              <li key={item.id}>
                <span>{item.title}</span>
                <button type="button" className="lc-btn-sm lc-btn-subtle" onClick={() => detach(item)} disabled={Boolean(busy)}>{t("detachClass")}</button>
              </li>
            ))}
          </ul>
        ) : <p className="lc-empty-notice">{t("noGroupedClasses")}</p>}
        <form className="lc-form-row lc-teaching-course-attach" onSubmit={attach}>
          <div className="lc-form-group">
            <label htmlFor={`teaching-course-class-${teachingCourse.id}`}>{t("chooseManageableClass")}</label>
            <select id={`teaching-course-class-${teachingCourse.id}`} className="lc-select" value={classId} onChange={(event) => setClassId(event.target.value)}>
              <option value="">{t("chooseManageableClass")}</option>
              {manageableClasses.map((item) => <option key={item.id} value={String(item.id)}>{item.title}</option>)}
            </select>
          </div>
          <button type="submit" className="lc-btn-sm lc-btn-outline" disabled={!classId || Boolean(busy)}>{t("attachMove")}</button>
        </form>
      </div>
    </article>
  );
}

function TeachingCoursesSection({
  teachingCourses,
  classes,
  apiRoot,
  run,
  busy,
  refresh,
}: {
  teachingCourses: TeachingCourseDetail[];
  classes: CourseSummary[];
  apiRoot: string;
  run: RunAction;
  busy: string | null;
  refresh: () => Promise<void>;
}) {
  const t = useWorkspaceText();
  const manageableClasses = classes.filter((item) => item.can_manage === true);
  const groupedIds = new Set(teachingCourses.flatMap((item) => item.classes.map((classItem) => classItem.id)));
  const ungrouped = manageableClasses.filter((item) => !groupedIds.has(item.id));

  return (
    <section className="lc-teaching-courses" aria-labelledby="teaching-courses-heading">
      <h2 id="teaching-courses-heading">{t("courses")}</h2>
      <form className="lc-form" onSubmit={(event) => {
        event.preventDefault();
        const formElement = event.currentTarget;
        const form = new FormData(formElement);
        const title = String(form.get("title") ?? "").trim();
        if (!title) return;
        void run("teaching-course-create", async (key) => {
          await postJson(endpoint(apiRoot, "teaching-courses/"), {
            title,
            description: String(form.get("description") ?? ""),
          }, key);
          formElement.reset();
          await refresh();
        });
      }}>
        <div className="lc-form-row">
          <div className="lc-form-group">
            <label htmlFor="workspace-new-course-title">{t("courseTitle")}</label>
            <input id="workspace-new-course-title" name="title" className="lc-input" required maxLength={200} />
          </div>
          <div className="lc-form-group">
            <label htmlFor="workspace-new-course-description">{t("description")}</label>
            <input id="workspace-new-course-description" name="description" className="lc-input" />
          </div>
        </div>
        <button type="submit" className="lc-btn-sm lc-btn-primary" disabled={Boolean(busy)}>{t("createCourse")}</button>
      </form>
      {teachingCourses.length ? (
        <div className="lc-teaching-course-list">
          {teachingCourses.map((item) => (
            <TeachingCourseCard key={item.id} teachingCourse={item} manageableClasses={manageableClasses} apiRoot={apiRoot} run={run} busy={busy} refresh={refresh} />
          ))}
        </div>
      ) : <p className="lc-empty-notice">{t("noCourses")}</p>}
      <div className="lc-ungrouped-classes">
        <h3>{t("ungroupedClasses")}</h3>
        {ungrouped.length ? <ul>{ungrouped.map((item) => <li key={item.id}>{item.title}</li>)}</ul> : <p className="lc-empty-notice">{t("noUngroupedClasses")}</p>}
      </div>
    </section>
  );
}

function TeacherWorkspace({ apiRoot, builderUrl }: { apiRoot: string; builderUrl: string }) {
  const t = useWorkspaceText();
  const [tab, setTab] = useState<"lessons" | "shared" | "classes" | "recent">("lessons");
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [teachingCourses, setTeachingCourses] = useState<TeachingCourseDetail[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [flows, setFlows] = useState<FlowSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [composer, setComposer] = useState<{ flowId?: number | null; sourceSessionId?: number | null; label: string } | null>(null);

  const loadAll = useCallback(async () => {
    const [workspace, flowData, teachingCourseData] = await Promise.all([
      getJson<WorkspacePayload>(endpoint(apiRoot, "workspace/")),
      getJson<{ flows: FlowSummary[] }>(endpoint(apiRoot, "flows/")),
      getJson<TeachingCoursesPayload>(endpoint(apiRoot, "teaching-courses/")),
    ]);
    const teachingCourseDetails = await Promise.all(
      (teachingCourseData.teaching_courses ?? []).map((item) => (
        getJson<TeachingCourseDetail>(endpoint(apiRoot, `teaching-courses/${item.id}/`))
      )),
    );
    setCourses(workspace.courses ?? []);
    setTeachingCourses(teachingCourseDetails);
    setSessions(workspace.sessions ?? []);
    setFlows(flowData.flows ?? []);
  }, [apiRoot]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    void loadAll()
      .catch((reason: unknown) => { if (!cancelled) setError(errorText(reason, t("loadFailed"))); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [loadAll, t]);

  const run: RunAction = useCallback(async (operation, action) => {
    setBusy(operation);
    setError("");
    setNotice("");
    try {
      await action(operationKey(operation));
      setNotice(t("saved"));
    } catch (reason) {
      setError(errorText(reason, t("unknownError")));
    } finally {
      setBusy(null);
    }
  }, [t]);

  const refresh = useCallback(async () => {
    await loadAll();
  }, [loadAll]);

  const createSession = async (values: SessionCreateValues) => {
    await run("session-create", async (key) => {
      const body = {
        title: values.title,
        course_id: values.courseId,
        flow_id: values.flowId,
        source_session_id: values.sourceSessionId,
        ...(values.accessMode ? { access_mode: values.accessMode } : {}),
        ...(values.admissionMode ? { admission_mode: values.admissionMode } : {}),
        ...(values.chatEnabled === undefined ? {} : { chat_enabled: values.chatEnabled }),
      };
      const created = await postJson<SessionSummary>(endpoint(apiRoot, "sessions/"), body, key);
      window.location.assign(created.console_url);
    });
  };

  const openInstant = () => setComposer({ label: t("newInstant"), flowId: null, sourceSessionId: null });
  const openLesson = (flowId: number, demo = false) => setComposer({ label: demo ? t("useDemo") : t("fromLesson"), flowId, sourceSessionId: null });
  const openReuse = (session: SessionSummary) => setComposer({
    label: session.demo ? t("useDemo") : `${t("fromSession")}: ${session.title}`,
    flowId: session.demo ? session.flow_id ?? null : null,
    sourceSessionId: session.demo ? null : session.id,
  });
  const deleteSession = (session: SessionSummary) => {
    if (!session.can_delete) return;
    const message = t("deleteConfirm").replace("{title}", session.title);
    if (!window.confirm(message)) return;
    void run(`session-delete-${session.id}`, async (key) => {
      await postJson(endpoint(apiRoot, `sessions/${session.id}/delete/`), { confirm: true }, key);
      await refresh();
    });
  };

  const visibleFlows = tab === "shared"
    ? flows.filter((flow) => flow.shared && !flow.demo)
    : flows.filter((flow) => !flow.shared || flow.demo);
  const emptyText = tab === "shared" ? t("noSharedLessons") : tab === "classes" ? t("noClasses") : tab === "recent" ? t("noRecentSessions") : t("noLessons");

  return (
    <div className="lc-wide lc-workspace-root">
      <LanguageSwitcher />
      <header className="lc-builder-topbar">
        <div className="lc-builder-title-group">
          <p className="lc-kicker">{t("workspace")}</p>
          <h1>{t("workspace")}</h1>
        </div>
        <a className="lc-btn lc-btn-outline" href={builderUrl}>{useLocale().startsWith("zh") ? "创建教案" : "Create lesson"}</a>
        <button type="button" className="lc-btn-sm lc-btn-primary" onClick={openInstant} disabled={Boolean(busy)}>{t("newInstant")}</button>
      </header>
      {error ? <p className="lc-form-error" role="alert">{error}</p> : null}
      {notice ? <p className="lc-builder-status lc-builder-status-success" aria-live="polite">{notice}</p> : null}
      {composer ? (
        <SessionComposer
          key={`${composer.flowId ?? "instant"}:${composer.sourceSessionId ?? "new"}`}
          seed={composer}
          courses={courses}
          busy={busy === "session-create"}
          onCancel={() => setComposer(null)}
          onCreate={createSession}
        />
      ) : null}
      <nav className="lc-workspace-tabs" aria-label={t("workspace")}>
        {(["lessons", "shared", "classes", "recent"] as const).map((item) => {
          const label = item === "lessons" ? t("lessons") : item === "shared" ? t("sharedWithMe") : item === "classes" ? t("classes") : t("recentSessions");
          return (
            <button key={item} type="button" className={tab === item ? "lc-btn-sm lc-btn-primary" : "lc-btn-sm lc-btn-outline"} aria-selected={tab === item} onClick={() => setTab(item)}>
              {label}
            </button>
          );
        })}
      </nav>
      {loading ? <p>{t("loading")}</p> : tab === "classes" ? (
        <>
          <TeachingCoursesSection teachingCourses={teachingCourses} classes={courses} apiRoot={apiRoot} run={run} busy={busy} refresh={refresh} />
          <section className="lc-workspace-create-class">
            <h2>{t("createClass")}</h2>
            <form className="lc-form" onSubmit={(event) => {
              event.preventDefault();
              const formElement = event.currentTarget;
              const form = new FormData(formElement);
              const title = String(form.get("title") ?? "").trim();
              if (!title) return;
              void run("course-create", async (key) => {
                await postJson(endpoint(apiRoot, "courses/"), { title, description: String(form.get("description") ?? "") }, key);
                formElement.reset();
                await refresh();
              });
            }}>
              <div className="lc-form-row">
                <div className="lc-form-group">
                  <label htmlFor="workspace-new-class-title">{t("classTitle")}</label>
                  <input id="workspace-new-class-title" name="title" className="lc-input" required maxLength={200} />
                </div>
                <div className="lc-form-group">
                  <label htmlFor="workspace-new-class-description">{t("description")}</label>
                  <input id="workspace-new-class-description" name="description" className="lc-input" />
                </div>
              </div>
              <button type="submit" className="lc-btn-sm lc-btn-primary" disabled={Boolean(busy)}>{t("createClass")}</button>
            </form>
          </section>
          {courses.length ? <div className="lc-grid">{courses.map((course) => <CourseCard key={course.id} course={course} flows={flows} apiRoot={apiRoot} run={run} busy={busy} />)}</div> : <p className="lc-empty-notice">{emptyText}</p>}
        </>
      ) : tab === "recent" ? (
        sessions.length ? (
          <div className="lc-grid">
            {sessions.map((session) => (
              <article className="lc-card lc-workspace-item" key={session.id}>
                <h2>{session.title} {session.demo ? <span className="lc-badge">{t("publicDemo")}</span> : null}</h2>
                <p><span className="lc-badge">{session.status}</span>{session.course_id ? ` · ${courses.find((course) => course.id === session.course_id)?.title ?? t("class")}` : ""}</p>
                <div className="lc-actions">
                  {(session.demo || session.capabilities?.includes("manage_session")) && <button type="button" className="lc-btn-sm lc-btn-primary" onClick={() => openReuse(session)} disabled={Boolean(busy)}>{session.demo ? t("useDemo") : t("reuseSession")}</button>}
                  <a className="lc-btn-sm lc-btn-outline" href={session.console_url}>{t("status")}</a>
                  {session.can_delete ? <button type="button" className="lc-btn-sm lc-btn-danger" onClick={() => deleteSession(session)} disabled={Boolean(busy)}>{t("delete")}</button> : null}
                </div>
              </article>
            ))}
          </div>
        ) : <p className="lc-empty-notice">{emptyText}</p>
      ) : visibleFlows.length ? (
        <div className="lc-grid">
          {visibleFlows.map((flow) => <LessonCard key={flow.id} flow={flow} apiRoot={apiRoot} builderUrl={builderUrl} run={run} busy={busy} onStart={openLesson} onRefresh={refresh} />)}
        </div>
      ) : <p className="lc-empty-notice">{emptyText}</p>}
    </div>
  );
}

export function mountTeacherWorkspace(el: HTMLElement): void {
  const apiRoot = normalizeApiRoot(el.dataset.apiRoot ?? "/api/v1/");
  const builderUrl = el.dataset.builderUrl;
  if (!builderUrl) return;
  const locale: Locale = getLocale(el);
  const root = createRoot(el);
  root.render(
    <LocaleProvider initial={locale} root={el}>
      <TeacherWorkspace apiRoot={apiRoot} builderUrl={builderUrl} />
    </LocaleProvider>,
  );
  el.addEventListener("liveclassroom:unmount", () => root.unmount(), { once: true });
}
