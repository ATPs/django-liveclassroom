import * as React from "react";
import { useLocale } from "../../i18n.js";
import { useUnsavedChangesWarning, useUnsavedNavigationGuard } from "../../navigation.js";

type Draft = { dirty: boolean; save: () => Promise<boolean>; discard: () => void };
const DraftContext = React.createContext<((id: string, draft: Draft | null) => void) | null>(null);

/** One departure transaction covers all independently editable workspace forms. */
export function WorkspaceDrafts({ children }: { children: React.ReactNode }) {
  const drafts = React.useRef(new Map<string, Draft>());
  const [dirty, setDirty] = React.useState(false);
  const zh = useLocale().startsWith("zh");
  const register = React.useCallback((id: string, draft: Draft | null) => {
    if (draft) drafts.current.set(id, draft); else drafts.current.delete(id);
    setDirty([...drafts.current.values()].some(value => value.dirty));
  }, []);
  useUnsavedChangesWarning(dirty);
  const guard = useUnsavedNavigationGuard({ dirty,
    onSave: async () => {
      for (const draft of [...drafts.current.values()]) if (draft.dirty && !await draft.save()) return false;
      return true;
    },
    onBeforeLeave: () => { for (const draft of drafts.current.values()) draft.discard(); },
    labels: zh ? { title: "未保存的更改", body: "离开前保存所有已修改的表单？", save: "保存并离开", discard: "放弃并离开", stay: "留在此页" } : {},
  });
  return <DraftContext.Provider value={register}>{children}{guard.dialog}</DraftContext.Provider>;
}

export function useWorkspaceDraft(id: string, draft: Draft): void {
  const register = React.useContext(DraftContext);
  React.useEffect(() => { register?.(id, draft); });
  React.useEffect(() => () => register?.(id, null), [id, register]);
}

/** The existing async form workflow acknowledges success via reset(). */
export function WorkspaceCreateForm({ children, ...props }: React.FormHTMLAttributes<HTMLFormElement>) {
  const id = React.useId();
  const form = React.useRef<HTMLFormElement>(null);
  const [dirty, setDirty] = React.useState(false);
  const pending = React.useRef<((saved: boolean) => void) | null>(null);
  useWorkspaceDraft(id, { dirty,
    save: () => new Promise<boolean>(resolve => {
      if (!form.current?.reportValidity()) { resolve(false); return; }
      pending.current = resolve;
      form.current.requestSubmit();
      // Submission errors must keep the current page and the draft. A slow
      // request may still complete, but never causes a delayed departure.
      window.setTimeout(() => { if (pending.current === resolve) { pending.current = null; resolve(false); } }, 15000);
    }),
    discard: () => { form.current?.reset(); setDirty(false); },
  });
  return <form {...props} ref={form} onChange={event => { setDirty(true); props.onChange?.(event); }} onReset={event => {
    setDirty(false); pending.current?.(true); pending.current = null; props.onReset?.(event);
  }}>{children}</form>;
}
