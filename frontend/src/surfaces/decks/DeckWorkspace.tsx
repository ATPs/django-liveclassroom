import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import { MarkdownView } from "../../activities/MarkdownView.js";
import { LanguageSwitcher, LocaleProvider, useLocale } from "../../i18n.js";
import { deleteJson, getJson, patchJson, postJson, putJson } from "../../protocol.js";

type Asset = { id: string; name: string; kind: string };
type Slide = { key: string; position: number; markdown: string; notes?: string; asset_ids: string[] };
type Deck = { id: number; title: string; theme: string; version: number; slides: Slide[] };
type DeckList = { decks: Deck[] };

const newKey = () => crypto.randomUUID();
const newSlide = (): Slide => ({ key: newKey(), position: 1, markdown: "# New slide", notes: "", asset_ids: [] });
const cleanSlides = (slides: Slide[]) => slides.map((slide, index) => ({ ...slide, position: index + 1 }));

function message(locale: string, en: string, zh: string) {
  return locale.startsWith("zh") ? zh : en;
}

function DeckWorkspace({ apiRoot, assetsUrl, previewTemplate }: { apiRoot: string; assetsUrl: string; previewTemplate: string }) {
  const locale = useLocale();
  const tr = (en: string, zh: string) => message(locale, en, zh);
  const [decks, setDecks] = useState<Deck[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [deck, setDeck] = useState<Deck | null>(null);
  const [selected, setSelected] = useState(0);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const refresh = () => Promise.all([getJson<DeckList>(apiRoot), getJson<{ assets: Asset[] }>(assetsUrl)])
    .then(([deckResult, assetResult]) => {
      setDecks(deckResult.decks);
      setAssets(assetResult.assets);
      return deckResult.decks;
    })
    .catch((error: unknown) => setStatus(error instanceof Error ? error.message : tr("Could not load decks.", "无法加载幻灯片。")));

  useEffect(() => { void refresh(); }, [apiRoot, assetsUrl]);

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
  const selectDeck = (next: Deck) => { setDeck({ ...next, slides: cleanSlides(next.slides) }); setSelected(0); setDirty(false); setStatus(""); };
  const create = () => selectDeck({ id: 0, title: tr("Untitled deck", "未命名幻灯片"), theme: "default", version: 0, slides: [newSlide()] });
  const move = (offset: number) => {
    if (!deck || selected + offset < 0 || selected + offset >= deck.slides.length) return;
    const slides = [...deck.slides];
    [slides[selected], slides[selected + offset]] = [slides[selected + offset], slides[selected]];
    edit({ slides: cleanSlides(slides) }); setSelected(selected + offset);
  };
  const save = async () => {
    if (!deck || !deck.title.trim()) { setStatus(tr("A deck title is required.", "请填写幻灯片标题。")); return; }
    setSaving(true); setStatus("");
    const body = { title: deck.title.trim(), theme: deck.theme, slides: cleanSlides(deck.slides).map(({ key, markdown, notes, asset_ids }) => ({ key, markdown, notes, asset_ids })) };
    try {
      let saved: Deck;
      if (!deck.id) saved = await postJson<Deck>(apiRoot, body, crypto.randomUUID());
      else {
        const changed = await patchJson<Deck>(`${apiRoot}${deck.id}/`, { title: body.title, theme: body.theme, expected_version: deck.version }, crypto.randomUUID());
        saved = await putJson<Deck>(`${apiRoot}${deck.id}/slides/`, { expected_version: changed.version, slides: body.slides }, crypto.randomUUID());
      }
      await refresh(); selectDeck(saved); setStatus(tr("Deck saved.", "幻灯片已保存。"));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : tr("Save failed; your draft is still here.", "保存失败；草稿仍已保留。"));
    } finally { setSaving(false); }
  };
  const copy = async () => {
    if (!deck?.id) return;
    try { selectDeck(await postJson<Deck>(`${apiRoot}${deck.id}/copy/`, {}, crypto.randomUUID())); await refresh(); }
    catch (error) { setStatus(error instanceof Error ? error.message : tr("Copy failed.", "复制失败。")); }
  };
  const remove = async () => {
    if (!deck?.id || !window.confirm(tr("Delete this deck?", "删除这份幻灯片？"))) return;
    try { await deleteJson(`${apiRoot}${deck.id}/`, crypto.randomUUID()); setDeck(null); setDirty(false); await refresh(); }
    catch (error) { setStatus(error instanceof Error ? error.message : tr("Delete failed.", "删除失败。")); }
  };

  return <div className="lc-deck-root">
    <LanguageSwitcher />
    <header className="lc-builder-topbar"><div><h2>{tr("Slide decks", "幻灯片")}</h2><p>{dirty ? tr("Unsaved changes", "有未保存的更改") : tr("Reusable private drafts", "可复用的私有草稿")}</p></div><button className="lc-btn" onClick={create}>{tr("New deck", "新建幻灯片")}</button></header>
    {status && <p className="lc-builder-status-error" role="status">{status}</p>}
    <div className="lc-deck-layout">
      <aside className="lc-deck-list"><h3>{tr("Your decks", "我的幻灯片")}</h3>{!decks.length && <p>{tr("Create your first deck.", "创建第一份幻灯片。")}</p>}{decks.map((item) => <button key={item.id} className={deck?.id === item.id ? "lc-deck-selected" : ""} onClick={() => selectDeck(item)}>{item.title}</button>)}</aside>
      {deck && <main className="lc-deck-editor">
        <div className="lc-deck-toolbar"><label>{tr("Title", "标题")}<input value={deck.title} onChange={(event) => edit({ title: event.target.value })} /></label><div className="lc-actions"><button onClick={save} disabled={saving}>{tr("Save", "保存")}</button>{deck.id > 0 && <><button onClick={copy}>{tr("Copy", "复制")}</button><button className="lc-btn-danger" onClick={remove}>{tr("Delete", "删除")}</button></>}</div></div>
        <div className="lc-deck-edit-layout"><section className="lc-deck-slides"><div className="lc-actions"><h3>{tr("Slides", "页面")}</h3><button onClick={() => { edit({ slides: [...deck.slides, { ...newSlide(), position: deck.slides.length + 1 }] }); setSelected(deck.slides.length); }}>{tr("Add slide", "添加页面")}</button></div>{deck.slides.map((slide, index) => <button key={slide.key} className={index === selected ? "lc-deck-selected" : ""} onClick={() => setSelected(index)}>{index + 1}. {slide.markdown.split("\n")[0].replace(/^#+\s*/, "") || tr("Slide", "页面")}</button>)}</section>
          {currentSlide && <section className="lc-deck-slide-form"><div className="lc-actions"><button onClick={() => move(-1)} disabled={selected === 0}>{tr("Move up", "上移")}</button><button onClick={() => move(1)} disabled={selected === deck.slides.length - 1}>{tr("Move down", "下移")}</button><button onClick={() => { edit({ slides: deck.slides.filter((_, index) => index !== selected) }); setSelected(Math.max(0, selected - 1)); }} disabled={deck.slides.length === 1}>{tr("Delete slide", "删除页面")}</button></div><label>{tr("Markdown", "Markdown")}<textarea aria-label={tr("Markdown", "Markdown")} rows={13} value={currentSlide.markdown} onChange={(event) => editSlide({ markdown: event.target.value })} /></label><label>{tr("Private presenter notes", "仅演讲者可见的备注")}<textarea aria-label={tr("Private presenter notes", "仅演讲者可见的备注")} rows={4} value={currentSlide.notes ?? ""} onChange={(event) => editSlide({ notes: event.target.value })} /></label><fieldset><legend>{tr("Attached files", "附加文件")}</legend>{!assets.length && <p>{tr("Upload a reusable file from a lesson first.", "请先从教案上传可复用文件。")}</p>}{assets.map((asset) => <label key={asset.id}><input type="checkbox" checked={currentSlide.asset_ids.includes(asset.id)} onChange={(event) => editSlide({ asset_ids: event.target.checked ? [...currentSlide.asset_ids, asset.id] : currentSlide.asset_ids.filter((id) => id !== asset.id) })} /> {asset.name}</label>)}</fieldset></section>}</div>
        <section className="lc-deck-preview"><h3>{tr("Preview", "预览")}</h3><MarkdownView markdown={currentSlide?.markdown ?? ""} />{previewUrl ? <iframe title={tr("Slide preview", "幻灯片预览")} src={previewUrl} className="lc-deck-iframe" /> : <p>{tr("Save to open full VaultPub Slide View.", "保存后可打开完整 VaultPub 幻灯片视图。")}</p>}</section>
      </main>}
      {!deck && <main><p>{tr("Select a deck or create one to start.", "选择或新建幻灯片以开始。")}</p></main>}
    </div>
  </div>;
}

export function mountDeckWorkspace(element: HTMLElement) {
  const { apiRoot, assetsUrl, previewTemplate, locale = "en" } = element.dataset;
  if (!apiRoot || !assetsUrl || !previewTemplate) return;
  createRoot(element).render(<LocaleProvider initial={locale.startsWith("zh") ? "zh-Hans" : "en"} root={element}><DeckWorkspace apiRoot={apiRoot} assetsUrl={assetsUrl} previewTemplate={previewTemplate} /></LocaleProvider>);
}
