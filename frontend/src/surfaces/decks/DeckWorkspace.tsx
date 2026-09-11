import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import { MarkdownView } from "../../activities/MarkdownView.js";
import { LanguageSwitcher, LocaleProvider, useLocale } from "../../i18n.js";
import { Breadcrumbs, routeUrl, updateLocation, useLocationPath, useNavigationHeading, useQuerySelection, useUnsavedChangesWarning, useUnsavedNavigationGuard } from "../../navigation.js";
import { deleteJson, getJson, patchJson, postJson, putJson } from "../../protocol.js";

type Asset = { id: string; name: string; kind: string };
type Slide = { key: string; position: number; markdown: string; notes?: string; asset_ids: string[] };
type Deck = { id: number; title: string; theme: string; version: number; slides: Slide[] };
type DeckList = { decks: Deck[] };
type ImportPreview = { draft: Omit<Deck, "id" | "version"> & { id?: number; version?: number }; errors: { slide: number | null; message: string }[]; valid: boolean };

const newKey = () => crypto.randomUUID();
const newSlide = (): Slide => ({ key: newKey(), position: 1, markdown: "# New slide", notes: "", asset_ids: [] });
const cleanSlides = (slides: Slide[]) => slides.map((slide, index) => ({ ...slide, position: index + 1 }));

function message(locale: string, en: string, zh: string) {
  return locale.startsWith("zh") ? zh : en;
}

function DeckWorkspace({ apiRoot, assetsUrl, previewTemplate, deckUrlTemplate, libraryUrl, initialDeckId = "" }: { apiRoot: string; assetsUrl: string; previewTemplate: string; deckUrlTemplate: string; libraryUrl: string; initialDeckId?: string }) {
  const locale = useLocale();
  const tr = (en: string, zh: string) => message(locale, en, zh);
  const [decks, setDecks] = useState<Deck[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [deck, setDeck] = useState<Deck | null>(null);
  const [selected, setSelected] = useState(0);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [importText, setImportText] = useState("");
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [includeNotes, setIncludeNotes] = useState(false);
  const [deckSelection] = useQuerySelection("deck", initialDeckId);
  const [slideSelection, selectSlideUrl] = useQuerySelection("slide");
  const locationPath = useLocationPath();
  const routeDeckId = React.useMemo(() => {
    const match = new URL(locationPath, window.location.href).pathname.match(/\/decks\/(\d+)\/?$/);
    return match ? Number(match[1]) : null;
  }, [locationPath]);

  const refresh = () => Promise.all([getJson<DeckList>(apiRoot), getJson<{ assets: Asset[] }>(assetsUrl)])
    .then(([deckResult, assetResult]) => {
      setDecks(deckResult.decks);
      setAssets(assetResult.assets);
      return deckResult.decks;
    })
    .catch((error: unknown) => setStatus(error instanceof Error ? error.message : tr("Could not load decks.", "无法加载幻灯片。")));

  useEffect(() => { void refresh(); }, [apiRoot, assetsUrl]);

  useEffect(() => {
    const selectedId = routeDeckId ?? (deckSelection ? Number(deckSelection) : null);
    if (!selectedId || deck?.id === selectedId) return;
    const matched = decks.find((item) => item.id === selectedId);
    if (matched) { setDeck({ ...matched, slides: cleanSlides(matched.slides) }); setSelected(0); setDirty(false); }
  }, [deck?.id, deckSelection, decks, routeDeckId]);

  useEffect(() => {
    if (!deck || !slideSelection) return;
    const index = deck.slides.findIndex((slide) => slide.key === slideSelection);
    if (index >= 0 && index !== selected) setSelected(index);
  }, [deck, selected, slideSelection]);

  useUnsavedChangesWarning(dirty);
  useNavigationHeading("lc-deck-heading");

  const currentSlide = deck?.slides[selected] ?? null;
  const previewUrl = useMemo(
    () => deck?.id ? previewTemplate.replace(/\/0\//, `/${deck.id}/`) : null,
    [deck?.id, previewTemplate],
  );
  const edit = (change: Partial<Deck>) => { if (deck) { setDeck({ ...deck, ...change }); setDirty(true); } };
  const editSlide = (change: Partial<Slide>) => {
    if (!deck || !currentSlide) return;
    const slides = deck.slides.map((slide, index) => index === selected ? { ...slide, ...change } : slide);
    edit({ slides });
  };
  const selectDeck = (next: Deck, updateUrl = true) => {
    setDeck({ ...next, slides: cleanSlides(next.slides) }); setSelected(0); setDirty(false); setStatus("");
    if (updateUrl && next.id) updateLocation(routeUrl(deckUrlTemplate.replace(/\/0\//, `/${next.id}/`), { deck: null, slide: null }), { focusId: "lc-deck-heading" });
  };
  const selectSlide = (index: number) => {
    setSelected(index);
    const slide = deck?.slides[index];
    if (slide) selectSlideUrl(slide.key);
  };
  const create = () => selectDeck({ id: 0, title: tr("Untitled deck", "未命名幻灯片"), theme: "default", version: 0, slides: [newSlide()] });
  const move = (offset: number) => {
    if (!deck || selected + offset < 0 || selected + offset >= deck.slides.length) return;
    const slides = [...deck.slides];
    [slides[selected], slides[selected + offset]] = [slides[selected + offset], slides[selected]];
    edit({ slides: cleanSlides(slides) }); setSelected(selected + offset);
  };
  const save = async (): Promise<boolean> => {
    if (!deck || !deck.title.trim()) { setStatus(tr("A deck title is required.", "请填写幻灯片标题。")); return false; }
    setSaving(true); setStatus("");
    const theme = ["default", "light", "dark"].includes(deck.theme) ? deck.theme : "default";
    const body = { title: deck.title.trim(), theme, slides: cleanSlides(deck.slides).map(({ key, markdown, notes, asset_ids }) => ({ key, markdown, notes, asset_ids })) };
    let acknowledgedVersion: number | null = null;
    try {
      let saved: Deck;
      if (!deck.id) saved = await postJson<Deck>(apiRoot, body, crypto.randomUUID());
      else {
        const changed = await patchJson<Deck>(`${apiRoot}${deck.id}/`, { title: body.title, theme: body.theme, expected_version: deck.version }, crypto.randomUUID());
        acknowledgedVersion = changed.version;
        saved = await putJson<Deck>(`${apiRoot}${deck.id}/slides/`, { expected_version: changed.version, slides: body.slides }, crypto.randomUUID());
      }
      await refresh(); selectDeck(saved, false); if (saved.id) updateLocation(routeUrl(deckUrlTemplate.replace(/\/0\//, `/${saved.id}/`), { deck: null, slide: slideSelection || null }), { replace: true, focusId: "lc-deck-heading" }); setStatus(tr("Deck saved.", "幻灯片已保存。"));
      return true;
    } catch (error) {
      if (acknowledgedVersion !== null) {
        setDeck({ ...deck, version: acknowledgedVersion });
        setDirty(true);
        setStatus(tr("Details saved, but slides are still local. Retry to save them.", "详情已保存，但幻灯片仍在本地。请重试保存。"));
        return false;
      }
      setStatus(error instanceof Error ? error.message : tr("Save failed; your draft is still here.", "保存失败；草稿仍已保留。"));
      return false;
    } finally { setSaving(false); }
  };
  const { requestNavigation, dialog: unsavedDialog } = useUnsavedNavigationGuard({ dirty, onSave: save, labels: {
    title: tr("Unsaved deck changes", "未保存的幻灯片更改"),
    body: tr("Save this deck before opening another one?", "打开另一份幻灯片前保存当前更改？"),
    save: tr("Save and open", "保存并打开"),
    discard: tr("Discard and open", "放弃并打开"),
    stay: tr("Stay", "留在此处"),
  } });
  const copy = async () => {
    if (!deck?.id) return;
    try { selectDeck(await postJson<Deck>(`${apiRoot}${deck.id}/copy/`, {}, crypto.randomUUID())); await refresh(); }
    catch (error) { setStatus(error instanceof Error ? error.message : tr("Copy failed.", "复制失败。")); }
  };
  const remove = async () => {
    if (!deck?.id || !window.confirm(tr("Delete this deck?", "删除这份幻灯片？"))) return;
    try { await deleteJson(`${apiRoot}${deck.id}/`, crypto.randomUUID()); setDeck(null); setDirty(false); updateLocation(routeUrl(libraryUrl, { slide: null }), { replace: true, focusId: "lc-deck-heading" }); await refresh(); }
    catch (error) { setStatus(error instanceof Error ? error.message : tr("Delete failed.", "删除失败。")); }
  };
  const previewImport = async () => {
    setStatus("");
    try {
      const result = await postJson<ImportPreview>(`${apiRoot}import/preview/`, {
        text: importText,
        assets: assets.map((asset) => asset.id),
      }, crypto.randomUUID());
      setImportPreview(result);
      setStatus(result.valid ? tr("Import is ready. Review it, then create the deck.", "导入已准备好。检查后创建幻灯片。") : tr("Review the import errors before creating a deck.", "创建幻灯片前请检查导入错误。"));
    } catch (error) {
      setImportPreview(null);
      setStatus(error instanceof Error ? error.message : tr("Import preview failed.", "导入预览失败。"));
    }
  };
  const commitImport = async () => {
    if (!importPreview?.valid) return;
    try {
      const saved = await postJson<Deck>(`${apiRoot}import/`, { draft: importPreview.draft }, crypto.randomUUID());
      await refresh();
      selectDeck(saved);
      setImportText("");
      setImportPreview(null);
      setStatus(tr("Deck imported.", "幻灯片已导入。"));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : tr("Deck import failed.", "幻灯片导入失败。"));
    }
  };
  const exportDeck = () => {
    if (!deck?.id) return;
    const url = `${apiRoot}${deck.id}/export/?include_notes=${includeNotes ? "1" : "0"}`;
    const link = document.createElement("a");
    link.href = url;
    link.download = `${deck.title.trim() || "deck"}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  return <div className="lc-deck-root">
    <LanguageSwitcher />
    <Breadcrumbs items={[{ href: libraryUrl, label: tr("Library", "资料库") }, { label: tr("Slide decks", "幻灯片") }]} />
    <header className="lc-builder-topbar"><div><h1 id="lc-deck-heading" tabIndex={-1}>{tr("Slide decks", "幻灯片")}</h1><p>{dirty ? tr("Unsaved changes", "有未保存的更改") : tr("Reusable private drafts", "可复用的私有草稿")}</p></div><button className="lc-btn" onClick={() => requestNavigation(create)}>{tr("New deck", "新建幻灯片")}</button></header>
    {status && <p className="lc-builder-status-error" role="status">{status}</p>}
    <div className="lc-deck-layout">
      <aside className="lc-deck-list"><h3>{tr("Your decks", "我的幻灯片")}</h3>{!decks.length && <p>{tr("Create your first deck.", "创建第一份幻灯片。")}</p>}{decks.map((item) => <button key={item.id} className={deck?.id === item.id ? "lc-deck-selected" : ""} onClick={() => requestNavigation(() => selectDeck(item))}>{item.title}</button>)}</aside>
      {deck && <section className="lc-deck-editor">
        <div className="lc-deck-toolbar"><label>{tr("Title", "标题")}<input value={deck.title} onChange={(event) => edit({ title: event.target.value })} /></label><label>{tr("Theme", "主题")}<select value={["default", "light", "dark"].includes(deck.theme) ? deck.theme : "default"} onChange={(event) => edit({ theme: event.target.value })}><option value="default">{tr("Default (light)", "默认（浅色）")}</option><option value="light">{tr("Light", "浅色")}</option><option value="dark">{tr("Dark", "深色")}</option></select></label><div className="lc-actions"><button onClick={() => void save()} disabled={saving}>{tr("Save", "保存")}</button>{deck.id > 0 && <><button onClick={copy}>{tr("Copy", "复制")}</button><button onClick={exportDeck}>{tr("Export Markdown", "导出 Markdown")}</button><label><input type="checkbox" checked={includeNotes} onChange={(event) => setIncludeNotes(event.target.checked)} /> {tr("Include private notes", "包含私密备注")}</label><button className="lc-btn-danger" onClick={remove}>{tr("Delete", "删除")}</button></>}</div></div>
        <div className="lc-deck-edit-layout"><section className="lc-deck-slides"><div className="lc-actions"><h3>{tr("Slides", "页面")}</h3><button onClick={() => { edit({ slides: [...deck.slides, { ...newSlide(), position: deck.slides.length + 1 }] }); selectSlide(deck.slides.length); }}>{tr("Add slide", "添加页面")}</button></div>{deck.slides.map((slide, index) => <button key={slide.key} className={index === selected ? "lc-deck-selected" : ""} onClick={() => selectSlide(index)}>{index + 1}. {slide.markdown.split("\n")[0].replace(/^#+\s*/, "") || tr("Slide", "页面")}</button>)}</section>
          {currentSlide && <section className="lc-deck-slide-form"><div className="lc-actions"><button onClick={() => move(-1)} disabled={selected === 0}>{tr("Move up", "上移")}</button><button onClick={() => move(1)} disabled={selected === deck.slides.length - 1}>{tr("Move down", "下移")}</button><button onClick={() => { edit({ slides: deck.slides.filter((_, index) => index !== selected) }); selectSlide(Math.max(0, selected - 1)); }} disabled={deck.slides.length === 1}>{tr("Delete slide", "删除页面")}</button></div><label>{tr("Markdown", "Markdown")}<textarea aria-label={tr("Markdown", "Markdown")} rows={13} value={currentSlide.markdown} onChange={(event) => editSlide({ markdown: event.target.value })} /></label><label>{tr("Private presenter notes", "仅演讲者可见的备注")}<textarea aria-label={tr("Private presenter notes", "仅演讲者可见的备注")} rows={4} value={currentSlide.notes ?? ""} onChange={(event) => editSlide({ notes: event.target.value })} /></label><fieldset><legend>{tr("Attached files", "附加文件")}</legend>{!assets.length && <p>{tr("Upload a reusable file from a lesson first.", "请先从教案上传可复用文件。")}</p>}{assets.map((asset) => <label key={asset.id}><input type="checkbox" checked={currentSlide.asset_ids.includes(asset.id)} onChange={(event) => editSlide({ asset_ids: event.target.checked ? [...currentSlide.asset_ids, asset.id] : currentSlide.asset_ids.filter((id) => id !== asset.id) })} /> {asset.name}</label>)}</fieldset></section>}</div>
        <section className="lc-deck-preview"><h3>{tr("Preview", "预览")}</h3><MarkdownView markdown={currentSlide?.markdown ?? ""} />{previewUrl ? <iframe title={tr("Slide preview", "幻灯片预览")} src={previewUrl} className="lc-deck-iframe" /> : <p>{tr("Save to open full VaultPub Slide View.", "保存后可打开完整 VaultPub 幻灯片视图。")}</p>}</section>
      </section>}
      {!deck && <section><p>{tr("Select a deck or create one to start.", "选择或新建幻灯片以开始。")}</p></section>}
    </div>
    <section className="lc-card lc-deck-portability" aria-label={tr("Markdown import", "Markdown 导入")}>
      <h3>{tr("Import a VaultPub Markdown deck", "导入 VaultPub Markdown 幻灯片")}</h3>
      <p>{tr("Use --- between slides. Fenced code separators stay in the same slide. Private notes use the explicit notes markers.", "使用 --- 分隔页面。代码块中的分隔线仍属于同一页面。私密备注使用明确的备注标记。")}</p>
      <textarea aria-label={tr("Markdown import", "Markdown 导入")} rows={8} value={importText} onChange={(event) => setImportText(event.target.value)} />
      <div className="lc-actions"><button onClick={previewImport} disabled={!importText.trim()}>{tr("Preview import", "预览导入")}</button><button onClick={commitImport} disabled={!importPreview?.valid}>{tr("Create imported deck", "创建导入幻灯片")}</button></div>
      {importPreview?.errors.length ? <ul role="alert">{importPreview.errors.map((error, index) => <li key={`${error.slide ?? "document"}-${index}`}>{error.slide ? `${tr("Slide", "页面")} ${error.slide}: ` : ""}{error.message}</li>)}</ul> : null}
    </section>
    {unsavedDialog}
  </div>;
}

export function mountDeckWorkspace(element: HTMLElement) {
  const { apiRoot, assetsUrl, previewTemplate, deckUrlTemplate, libraryUrl, locale = "en", deckId = "" } = element.dataset;
  if (!apiRoot || !assetsUrl || !previewTemplate || !deckUrlTemplate || !libraryUrl) return;
  createRoot(element).render(<LocaleProvider initial={locale.startsWith("zh") ? "zh-Hans" : "en"} root={element}><DeckWorkspace apiRoot={apiRoot} assetsUrl={assetsUrl} previewTemplate={previewTemplate} deckUrlTemplate={deckUrlTemplate} libraryUrl={libraryUrl} initialDeckId={deckId} /></LocaleProvider>);
}
