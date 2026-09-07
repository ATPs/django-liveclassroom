import * as React from "react";
import { useCallback, useEffect, useState } from "react";
import { displayAnswer, record } from "../../activities/activityData.js";
import { ActivityEditor, type EditableSnapshot } from "../../activities/ActivityEditor.js";
import { useLocale } from "../../i18n.js";
import { apiEndpoint, getJson, postJson, type SessionState } from "../../protocol.js";

type Step = {id:number; key:string; position:number; title:string; snapshot:EditableSnapshot; launched:boolean; activity_id:number|null;activity_state:string|null};
type Plan = {session:{plan_version:number; capabilities:string[]};steps:Step[];can_update_lesson:boolean;can_pull_lesson:boolean};
type Change = {key:string;kind:string;title:string;conflict:boolean;before:unknown;after:unknown;before_labels?:string[];after_labels?:string[]};
type Comparison = {direction:string;token:string;changes:Change[]};

function ChangeContent({value, labels}: {value:unknown;labels?:string[]}) {
  const locale=useLocale();
  const tr=(en:string,zh:string)=>locale.startsWith("zh")?zh:en;
  if (labels) return <ol>{labels.map((label,index)=><li key={index}>{label}</li>)}</ol>;
  if (!value) return <p>{tr("No step", "无此步骤")}</p>;
  const snapshot=record(record(value).snapshot);
  const content=record(snapshot.content);
  const fields: Array<[string,string]> = [["prompt",tr("Prompt","题干")],["markdown","Markdown"],["url",tr("URL","链接")],["caption",tr("Caption","说明")],["answer",tr("Correct answer","正确答案")],["explanation_markdown",tr("Explanation","解析")],["duration_seconds",tr("Seconds","秒")],["minimum",tr("Minimum","最小值")],["maximum",tr("Maximum","最大值")]];
  return <div style={{overflowWrap:"anywhere"}}><strong>{String(snapshot.title??"")}</strong>
    {fields.filter(([key])=>content[key]!==undefined).map(([key,label])=><p key={key} style={{whiteSpace:"pre-wrap"}}>{label}: {displayAnswer(content[key])}</p>)}
    {Array.isArray(content.options)&&<ul>{content.options.map((option,index)=>{const item=record(option);return <li key={index}>{typeof option==="string"?option:`${item.id}: ${item.text}`}</li>;})}</ul>}
  </div>;
}

export function SessionPlanPanel({stateUrl, state, onRefresh}: {stateUrl:string;state:SessionState|null;onRefresh:()=>Promise<void>}) {
  const locale = useLocale();
  const tr = (en:string,zh:string) => locale.startsWith("zh") ? zh : en;
  const [plan,setPlan] = useState<Plan|null>(null);
  const [editor,setEditor] = useState<Step|"new"|null>(null);
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  const [comparison,setComparison] = useState<Comparison|null>(null);
  const [selected,setSelected] = useState<string[]>([]);
  const [saveTitle,setSaveTitle] = useState("");
  const [library,setLibrary] = useState<Array<{id:number;title:string}>>([]);
  const [libraryId,setLibraryId] = useState("");
  const endpoint = useCallback((tail:string) => apiEndpoint(stateUrl, `sessions/${tail}`),[stateUrl]);
  const reload = useCallback(async () => { setPlan(await getJson<Plan>(endpoint("plan"))); },[endpoint]);
  useEffect(() => { void reload().catch(e => setError(e.message)); },[reload,state?.state_version]);
  const manage = plan?.session.capabilities.includes("manage_session") ?? false;
  const ended = state?.session.status === "ended";
  const execute = async (action:()=>Promise<unknown>) => {
    if (busy) return;
    setBusy(true);setError("");
    try { await action();await reload();await onRefresh(); }
    catch(e) { setError(e instanceof Error ? e.message : tr("Request failed","操作失败")); }
    finally {setBusy(false);}
  };
  const post = (url:string,body:Record<string,unknown>) => postJson(url,body,globalThis.crypto?.randomUUID?.() ?? `plan-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const save = async (snapshot:EditableSnapshot) => {
    if (!plan) return;
    if (editor === "new") await post(endpoint("plan"),{snapshot,plan_version:plan.session.plan_version});
    else if (editor?.activity_id) await post(apiEndpoint(stateUrl,`activities/${editor.activity_id}/revise`),{definition:snapshot});
    else if (editor) await post(endpoint(`plan/${editor.id}`),{snapshot,plan_version:plan.session.plan_version});
    setEditor(null);await reload();await onRefresh();
  };
  const move = (index:number,delta:number) => {
    if (!plan) return;
    const keys=plan.steps.map(s=>s.key); const other=index+delta;
    [keys[index],keys[other]]=[keys[other],keys[index]];
    void execute(()=>post(endpoint("plan/reorder"),{keys,plan_version:plan.session.plan_version}));
  };
  const compare = (direction:string) => void execute(async()=>{
    const data=await getJson<Comparison>(`${endpoint("plan/compare")}?direction=${direction}`);
    setComparison(data);setSelected(data.changes.filter(c=>!c.conflict).map(c=>c.key));
  });
  return <section className="lc-plan-section" data-session-plan>
    <h2>{tr("This classroom's lesson","本次课堂教案")}</h2>
    {error && <p role="alert">{error}</p>}
    {editor && <section className="lc-editor-workspace" aria-label={tr("Edit this classroom", "编辑本次课堂")}>
      <aside className="lc-editor-outline"><p>{tr("Lesson outline", "教案目录")}</p>{plan?.steps.map(step => <button type="button" key={step.key} className={editor !== "new" && editor.id === step.id ? "lc-editor-outline-current" : ""} onClick={() => setEditor(step)}>{step.position}. {step.title}</button>)}</aside>
      <div className="lc-editor-form"><h3>{editor === "new" ? tr("Add activity", "添加活动") : tr("Edit this classroom", "编辑本次内容")}</h3><ActivityEditor key={editor === "new" ? "new" : editor.id} initial={editor === "new" ? undefined : editor.snapshot} onSave={save} onCancel={()=>setEditor(null)}/></div>
      <aside className="lc-editor-preview"><p>{tr("Preview", "预览")}</p>{editor === "new" ? <p>{tr("Choose an activity type and enter content to preview it after saving.", "选择活动类型并填写内容；保存后可预览。")}</p> : <ChangeContent value={{snapshot: editor.snapshot}} />}</aside>
    </section>}
    {plan?.steps.map((step,index)=><div key={step.key} className="lc-plan-step">
      <strong>{index+1}. {step.title}</strong> {step.launched && <small>{tr("Used in class","已开展")}</small>}
      {manage && <div className="lc-actions">
        {(["display","participants"] as const).map(channel=><button key={channel} disabled={busy||state?.session.status!=="live"} onClick={()=>void execute(()=>post(endpoint(`plan/${step.id}/launch`),{channel}))}>{channel==="display"?tr("Show on display","投屏"):tr("Send to students","发给学生")}</button>)}
        <button disabled={ended||busy||(step.launched&&step.activity_state!=="open")} onClick={()=>setEditor(step)}>{tr("Edit this classroom","编辑本次内容")}</button>
        {step.launched && <details><summary>{tr("Run again with fresh answers", "重新开展并收集新答案")}</summary>{(["display","participants"] as const).map(channel=><button key={channel} disabled={busy||state?.session.status!=="live"} onClick={()=>void execute(()=>post(endpoint(`plan/${step.id}/launch`),{channel,restart:true}))}>{channel==="display"?tr("Start again on display","重新开展并投屏"):tr("Start again for students","重新开展并发给学生")}</button>)}</details>}
        {!step.launched && <button disabled={ended||busy} onClick={()=>void execute(()=>post(endpoint(`plan/${step.id}`),{remove:true,plan_version:plan.session.plan_version}))}>{tr("Remove","移除")}</button>}
        <button aria-label={tr("Move up","上移")} disabled={ended||busy||index===0} onClick={()=>move(index,-1)}>↑</button>
        <button aria-label={tr("Move down","下移")} disabled={ended||busy||index===plan.steps.length-1} onClick={()=>move(index,1)}>↓</button>
      </div>}
    </div>)}
    {manage && <>
      <div className="lc-actions">
        <button disabled={ended||busy} onClick={()=>setEditor("new")}>{tr("Add activity","添加活动")}</button>
        <button disabled={ended||busy} onClick={()=>void execute(async()=>{
          const url=endpoint("plan").replace(/sessions\/\d+\/plan\/?$/, "activity-definitions/");
          const data=await getJson<{activities:Array<{id:number;title:string}>}>(url);setLibrary(data.activities);
        })}>{tr("Choose from library","从资料库选择")}</button>
        {plan?.can_pull_lesson && <button disabled={ended||busy} onClick={()=>compare("to_session")}>{tr("Update unused steps from lesson","从教案更新未讲内容")}</button>}
        {plan?.can_update_lesson && <button disabled={busy} onClick={()=>compare("to_lesson")}>{tr("Save improvements to lesson","保存改进到教案")}</button>}
      </div>
      {!!library.length && <form className="lc-form" onSubmit={e=>{e.preventDefault();void execute(()=>post(endpoint("plan"),{activity_definition_id:Number(libraryId),plan_version:plan?.session.plan_version}));}}>
        <label>{tr("Library activity or material","资料库活动或材料")}<select required value={libraryId} onChange={e=>setLibraryId(e.target.value)}><option value="">—</option>{library.map(a=><option key={a.id} value={a.id}>{a.title}</option>)}</select></label><button disabled={busy||!libraryId}>{tr("Add","添加")}</button>
      </form>}
      <form className="lc-form" onSubmit={e=>{e.preventDefault();void execute(async()=>{await post(endpoint("save-flow"),{title:saveTitle});setSaveTitle("");});}}>
        <label>{tr("Save a personal lesson copy","另存为个人教案")}<input required maxLength={200} value={saveTitle} onChange={e=>setSaveTitle(e.target.value)}/></label><button disabled={busy}>{tr("Save lesson copy","保存教案副本")}</button>
      </form>
      {comparison && <section aria-label={tr("Review changes","检查变更")}>
        <h3>{tr("Choose changes to apply","选择要应用的变更")}</h3>
        {!comparison.changes.length && <p>{tr("No changes","没有变更")}</p>}
        {comparison.changes.map(change=><label key={change.key} style={{display:"block"}}><input type="checkbox" checked={selected.includes(change.key)} onChange={e=>setSelected(old=>e.target.checked?[...old,change.key]:old.filter(k=>k!==change.key))}/>{change.title} · {({added:tr("Added","新增"),removed:tr("Removed","移除"),modified:tr("Modified","修改"),order:tr("Order","顺序")} as Record<string,string>)[change.kind]}{change.conflict && <strong> · {tr("Conflict: selecting replaces the target change","存在冲突：勾选将覆盖目标的修改")}</strong>}<details><summary>{tr("View changes", "查看修改内容")}</summary><p>{tr("Current", "当前内容")}</p><ChangeContent value={change.before} labels={change.before_labels}/><p>{tr("Proposed", "拟应用内容")}</p><ChangeContent value={change.after} labels={change.after_labels}/></details></label>)}
        <button disabled={busy||!selected.length} onClick={()=>void execute(async()=>{await post(endpoint("plan/compare"),{direction:comparison.direction,token:comparison.token,keys:selected,confirmed_conflicts:comparison.changes.filter(c=>c.conflict&&selected.includes(c.key)).map(c=>c.key)});setComparison(null);})}>{tr("Apply selected changes","应用所选变更")}</button>
        <button onClick={()=>setComparison(null)}>{tr("Cancel","取消")}</button>
      </section>}
    </>}
  </section>;
}
