import { requestApplicationNavigation } from "../../navigation.js";

/** Progressive enhancement for Django-rendered browse destinations. */
export function installBrowseForms(): void {
  for (const form of document.querySelectorAll<HTMLFormElement>("#liveclassroom-root .lc-session-filters")) {
    let timer: number | undefined;
    const apply = () => {
      const url = new URL(window.location.href);
      for (const [key, value] of new FormData(form)) {
        if (typeof value === "string" && value) url.searchParams.set(key, value);
        else url.searchParams.delete(key);
      }
      url.searchParams.delete("page");
      if (url.href !== window.location.href) requestApplicationNavigation(() => window.location.replace(url));
    };
    form.addEventListener("submit", event => { event.preventDefault(); window.clearTimeout(timer); apply(); });
    form.addEventListener("input", event => {
      if (!(event.target instanceof HTMLInputElement) || event.target.type !== "search") return;
      window.clearTimeout(timer);
      timer = window.setTimeout(apply, 300);
    });
    form.addEventListener("change", event => {
      if (event.target instanceof HTMLSelectElement) { window.clearTimeout(timer); apply(); }
    });
  }
}
