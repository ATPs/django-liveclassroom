import * as React from "react";
import { useEffect, useRef } from "react";
import { mountFilePicker } from "../file_picker.js";
import { useLocale } from "../i18n.js";

/** Mount the shared protected-file authoring control inside a React surface. */
export function FilePicker({
  endpoint,
  isSuperuser,
  includeChannels,
  onSuccess,
}: {
  endpoint: string;
  isSuperuser: boolean;
  includeChannels: boolean;
  onSuccess: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const successRef = useRef(onSuccess);
  const locale = useLocale();
  successRef.current = onSuccess;

  useEffect(() => {
    const container = host.current;
    if (!container) return undefined;
    container.replaceChildren();
    mountFilePicker(container, {
      locale,
      endpoint,
      allowServerPath: isSuperuser,
      includeChannels,
      onSuccess: () => successRef.current(),
    });
    return () => container.replaceChildren();
  }, [endpoint, includeChannels, isSuperuser, locale]);

  return <div className="lc-file-picker" ref={host} />;
}
