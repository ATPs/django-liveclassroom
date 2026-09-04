import { postJson, type ActivityState, type Audience, type PresentationNavigationMode, type SessionState } from "./protocol.js";
import { t, type Locale } from "./locales.js";

type FileAsset = {
  id: string;
  name: string;
  kind: string;
  size: number;
  content_url: string;
  download_url?: string;
};

type FileRendererOptions = {
  parent: HTMLElement;
  activity: ActivityState;
  audience: Audience;
  state?: SessionState;
  stateUrl?: string;
  locale: Locale;
  renderMarkdown: (markdown: string) => HTMLElement;
  presentationEndpoint?: string;
};

type PagedDocument = {
  pageCount: number;
  renderPage: (page: number) => Promise<HTMLElement>;
  destroy?: () => void;
};

type PresentationTarget = "display" | "participants" | "both";

const studentPagedPages = new Map<string, number>();

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function fileAsset(activity: ActivityState): FileAsset | null {
  const content = record(activity.definition.content);
  const raw = record(content.asset);
  const id = stringValue(raw.id);
  const name = stringValue(raw.name);
  const kind = stringValue(raw.kind);
  const contentUrl = stringValue(raw.content_url);
  if (!id || !name || !kind || !contentUrl) return null;
  return {
    id,
    name,
    kind,
    size: typeof raw.size === "number" && Number.isFinite(raw.size) ? raw.size : 0,
    content_url: contentUrl,
    download_url: stringValue(raw.download_url) || undefined,
  };
}

function sameOriginUrl(value: string): string | null {
  try {
    const url = new URL(value, window.location.href);
    return url.origin === window.location.origin ? url.toString() : null;
  } catch {
    return null;
  }
}

function staticUrl(path: string): string {
  const prefix = document.body.dataset.liveclassroomStaticUrl || "/static/";
  return new URL(path.replace(/^\/+/, ""), new URL(prefix, window.location.href)).toString();
}

function normalizedKind(asset: FileAsset): "pptx" | "pdf" | "markdown" | "video" | null {
  const kind = asset.kind.toLowerCase();
  const name = asset.name.toLowerCase();
  if (kind === "pptx" || kind === "presentation" || name.endsWith(".pptx")) return "pptx";
  if (kind === "pdf" || name.endsWith(".pdf")) return "pdf";
  if (kind === "md" || kind === "markdown" || name.endsWith(".md") || name.endsWith(".markdown")) return "markdown";
  if (kind === "video" || kind === "mp4" || kind === "webm" || name.endsWith(".mp4") || name.endsWith(".webm")) return "video";
  return null;
}

function clampPage(page: number, pageCount: number): number {
  return Math.min(Math.max(page, 0), Math.max(pageCount - 1, 0));
}

function presentationFor(options: FileRendererOptions): { page: number; navigationMode: PresentationNavigationMode } {
  const channel = options.audience === "student" ? "participants" : "display";
  const presentation = options.state?.channels?.[channel]?.presentation;
  const page = typeof presentation?.page === "number" && Number.isFinite(presentation.page)
    ? Math.max(0, Math.floor(presentation.page - 1))
    : 0;
  const navigationMode = presentation?.navigation_mode;
  return {
    page,
    navigationMode: navigationMode === "paged" || navigationMode === "scroll" ? navigationMode : "follow",
  };
}

function statusNode(): HTMLElement {
  const status = document.createElement("p");
  status.className = "lc-file-status";
  status.setAttribute("aria-live", "polite");
  return status;
}

async function fetchAsset(url: string, signal: AbortSignal): Promise<Response> {
  const response = await fetch(url, { credentials: "same-origin", signal });
  if (!response.ok) throw new Error("asset-unavailable");
  return response;
}

function downloadLink(asset: FileAsset, locale: Locale): HTMLAnchorElement | null {
  if (!asset.download_url) return null;
  const url = sameOriginUrl(asset.download_url);
  if (!url) return null;
  const link = document.createElement("a");
  link.className = "lc-file-download";
  link.href = url;
  link.textContent = t("fileDownload", locale);
  return link;
}

function createPageFrame(): HTMLElement {
  const frame = document.createElement("section");
  frame.className = "lc-file-page";
  return frame;
}

function renderPaginator(
  host: HTMLElement,
  page: number,
  pageCount: number,
  locale: Locale,
  onPage: (nextPage: number) => void,
): void {
  const controls = document.createElement("div");
  controls.className = "lc-file-pagination";
  const previous = document.createElement("button");
  previous.type = "button";
  previous.textContent = t("filePreviousPage", locale);
  previous.disabled = page <= 0;
  previous.addEventListener("click", () => onPage(page - 1));
  const label = document.createElement("span");
  label.textContent = `${t("filePage", locale)} ${page + 1} / ${pageCount}`;
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = t("fileNextPage", locale);
  next.disabled = page >= pageCount - 1;
  next.addEventListener("click", () => onPage(page + 1));
  controls.append(previous, label, next);
  host.append(controls);
}

function teacherPresentationControls(
  host: HTMLElement,
  page: number,
  pageCount: number,
  options: FileRendererOptions,
  notice: HTMLElement,
  onPage: (nextPage: number) => void,
): void {
  if (!options.presentationEndpoint) return;
  const controls = document.createElement("fieldset");
  controls.className = "lc-file-teacher-controls";
  const legend = document.createElement("legend");
  legend.textContent = t("filePresentationControls", options.locale);
  controls.append(legend);

  const targetLabel = document.createElement("label");
  targetLabel.textContent = `${t("fileTarget", options.locale)} `;
  const target = document.createElement("select");
  for (const [value, label] of [
    ["display", t("display", options.locale)],
    ["participants", t("participants", options.locale)],
    ["both", t("fileBoth", options.locale)],
  ] as const) {
    const item = document.createElement("option");
    item.value = value;
    item.textContent = label;
    target.append(item);
  }
  targetLabel.append(target);

  const modeLabel = document.createElement("label");
  modeLabel.textContent = `${t("fileStudentNavigation", options.locale)} `;
  const mode = document.createElement("select");
  for (const [value, label] of [
    ["follow", t("fileFollowTeacher", options.locale)],
    ["paged", t("filePaged", options.locale)],
    ["scroll", t("fileScroll", options.locale)],
  ] as const) {
    const item = document.createElement("option");
    item.value = value;
    item.textContent = label;
    mode.append(item);
  }
  mode.value = presentationFor(options).navigationMode;
  modeLabel.append(mode);

  const send = async (nextPage?: number, navigationMode?: PresentationNavigationMode): Promise<void> => {
    const selectedTarget = target.value as PresentationTarget;
    const channels = selectedTarget === "both" ? ["display", "participants"] : [selectedTarget];
    const body: Record<string, unknown> = { channels };
    if (nextPage !== undefined) body.page = nextPage + 1;
    if (navigationMode !== undefined) body.navigation_mode = navigationMode;
    for (const control of controls.querySelectorAll<HTMLButtonElement | HTMLSelectElement>("button, select")) control.disabled = true;
    try {
      await postJson(options.presentationEndpoint!, body);
      if (nextPage !== undefined) onPage(nextPage);
      notice.textContent = t("updated", options.locale);
    } catch (error) {
      notice.textContent = error instanceof Error ? error.message : t("fileUnavailable", options.locale);
    } finally {
      for (const control of controls.querySelectorAll<HTMLButtonElement | HTMLSelectElement>("button, select")) control.disabled = false;
    }
  };

  mode.addEventListener("change", () => void send(undefined, mode.value as PresentationNavigationMode));
  controls.append(targetLabel, modeLabel);
  host.append(controls);
  renderPaginator(host, page, pageCount, options.locale, (nextPage) => void send(nextPage));
}

function mountPagedDocument(host: HTMLElement, presentationDocument: PagedDocument, options: FileRendererOptions, notice: HTMLElement): void {
  const presentation = presentationFor(options);
  const mode = options.audience === "student" ? presentation.navigationMode : "follow";
  const studentPageKey = `${options.activity.id}:${options.activity.revision}`;
  const storedPage = mode === "paged" ? studentPagedPages.get(studentPageKey) : undefined;
  let localPage = clampPage(storedPage ?? presentation.page, presentationDocument.pageCount);
  const pages = document.createElement("div");
  pages.className = mode === "scroll" ? "lc-file-pages lc-file-pages-scroll" : "lc-file-pages";
  host.append(pages);

  const renderPage = async (page: number, target: HTMLElement): Promise<void> => {
    target.replaceChildren(statusNode());
    target.firstElementChild!.textContent = t("fileLoading", options.locale);
    try {
      const content = await presentationDocument.renderPage(page);
      if (target.isConnected) target.replaceChildren(content);
    } catch {
      if (target.isConnected) target.replaceChildren(document.createTextNode(t("fileRenderFailed", options.locale)));
    }
  };

  if (mode === "scroll") {
    if (!("IntersectionObserver" in window)) {
      for (let page = 0; page < presentationDocument.pageCount; page += 1) {
        const target = createPageFrame();
        pages.append(target);
        void renderPage(page, target);
      }
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        const page = Number((entry.target as HTMLElement).dataset.page);
        if (Number.isInteger(page)) void renderPage(page, entry.target as HTMLElement);
      }
    }, { rootMargin: "600px 0px" });
    for (let page = 0; page < presentationDocument.pageCount; page += 1) {
      const target = createPageFrame();
      target.dataset.page = String(page);
      target.append(textNode(`${t("filePage", options.locale)} ${page + 1}`));
      pages.append(target);
      observer.observe(target);
    }
    return;
  }

  const target = createPageFrame();
  pages.append(target);
  const navigation = document.createElement("div");
  navigation.className = "lc-file-navigation";
  host.append(navigation);
  const updatePage = (nextPage: number) => {
    localPage = clampPage(nextPage, presentationDocument.pageCount);
    if (mode === "paged") studentPagedPages.set(studentPageKey, localPage);
    target.dataset.page = String(localPage);
    void renderPage(localPage, target);
    navigation.replaceChildren();
    if (options.audience === "teacher") {
      teacherPresentationControls(navigation, localPage, presentationDocument.pageCount, options, notice, updatePage);
    } else if (options.audience === "student" && mode === "paged") {
      renderPaginator(navigation, localPage, presentationDocument.pageCount, options.locale, updatePage);
    }
  };
  updatePage(localPage);
}

function textNode(value: string): Text {
  return document.createTextNode(value);
}

async function loadPdf(url: string, signal: AbortSignal): Promise<PagedDocument> {
  const response = await fetchAsset(url, signal);
  const bytes = new Uint8Array(await response.arrayBuffer());
  const pdfjs = await import("pdfjs-dist/build/pdf.mjs");
  pdfjs.GlobalWorkerOptions.workerSrc = staticUrl("liveclassroom/pdf.worker.min.mjs");
  const document = await pdfjs.getDocument({ data: bytes }).promise;
  return {
    pageCount: document.numPages,
    async renderPage(pageNumber: number): Promise<HTMLElement> {
      const page = await document.getPage(pageNumber + 1);
      const scale = Math.min(Math.max(window.devicePixelRatio || 1, 1), 2);
      const viewport = page.getViewport({ scale });
      const canvas = documentCreateCanvas(viewport.width, viewport.height);
      const context = canvas.getContext("2d");
      if (!context) throw new Error("canvas-unavailable");
      await page.render({ canvasContext: context, viewport }).promise;
      canvas.className = "lc-file-pdf-page";
      canvas.style.width = `${viewport.width / scale}px`;
      canvas.style.height = `${viewport.height / scale}px`;
      return canvas;
    },
    destroy: () => { void document.destroy(); },
  };
}

function documentCreateCanvas(width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(width);
  canvas.height = Math.ceil(height);
  return canvas;
}

async function loadPptx(url: string, signal: AbortSignal, objectUrls: Set<string>): Promise<PagedDocument> {
  const response = await fetchAsset(url, signal);
  const bytes = new Uint8Array(await response.arrayBuffer());
  const [{ parse, slideToSvgFile }, { PresentationState }] = await Promise.all([
    import("@web-ppt/core"),
    import("@web-ppt/viewer-core"),
  ]);
  const presentation = await parse(bytes);
  // The state machine is intentionally static: classroom navigation selects slides only.
  new PresentationState(presentation, { animate: false, skipHidden: true });
  return {
    pageCount: presentation.slides.length,
    async renderPage(pageNumber: number): Promise<HTMLElement> {
      const svg = await slideToSvgFile(presentation, presentation.slides[pageNumber]);
      const objectUrl = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
      objectUrls.add(objectUrl);
      const frame = document.createElement("iframe");
      frame.className = "lc-file-pptx-page";
      frame.title = `Slide ${pageNumber + 1}`;
      frame.sandbox.value = "";
      frame.referrerPolicy = "no-referrer";
      frame.src = objectUrl;
      return frame;
    },
  };
}

function renderVideo(host: HTMLElement, url: string, asset: FileAsset): void {
  const video = document.createElement("video");
  video.className = "lc-file-video";
  video.controls = true;
  video.preload = "metadata";
  video.src = url;
  video.title = asset.name;
  host.append(video);
}

export function mountFileActivity(options: FileRendererOptions): () => void {
  const asset = fileAsset(options.activity);
  const host = document.createElement("section");
  host.className = "lc-file-activity";
  const notice = statusNode();
  host.append(notice);
  options.parent.append(host);
  const controller = new AbortController();
  const objectUrls = new Set<string>();
  let documentRenderer: PagedDocument | undefined;

  if (!asset) {
    notice.textContent = t("fileUnavailable", options.locale);
    return () => controller.abort();
  }
  const contentUrl = sameOriginUrl(asset.content_url);
  const kind = normalizedKind(asset);
  if (!contentUrl || !kind) {
    notice.textContent = t("fileUnavailable", options.locale);
    return () => controller.abort();
  }

  const download = options.audience === "teacher" ? downloadLink(asset, options.locale) : null;
  if (download) host.append(download);

  void (async () => {
    try {
      notice.textContent = t("fileLoading", options.locale);
      if (kind === "video") {
        notice.remove();
        renderVideo(host, contentUrl, asset);
        return;
      }
      if (kind === "markdown") {
        const response = await fetchAsset(contentUrl, controller.signal);
        const markdown = await response.text();
        if (!host.isConnected || controller.signal.aborted) return;
        notice.remove();
        host.append(options.renderMarkdown(markdown));
        return;
      }
      documentRenderer = kind === "pdf"
        ? await loadPdf(contentUrl, controller.signal)
        : await loadPptx(contentUrl, controller.signal, objectUrls);
      if (!host.isConnected || controller.signal.aborted) return;
      notice.textContent = "";
      mountPagedDocument(host, documentRenderer, options, notice);
    } catch (error) {
      if (controller.signal.aborted) return;
      notice.textContent = error instanceof Error && error.message === "asset-unavailable"
        ? t("fileUnavailable", options.locale)
        : t("fileRenderFailed", options.locale);
    }
  })();

  return () => {
    controller.abort();
    documentRenderer?.destroy?.();
    for (const objectUrl of objectUrls) URL.revokeObjectURL(objectUrl);
  };
}
