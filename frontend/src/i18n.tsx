import * as React from "react";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { setStoredLocale, t as translate, type Locale, type TranslationKey } from "./locales.js";

type LocaleState = {
  locale: Locale;
  setLocale: (next: Locale) => void;
};

const LocaleContext = createContext<LocaleState | null>(null);

export function LocaleProvider({
  initial,
  root,
  children,
}: {
  initial: Locale;
  root: HTMLElement | null;
  children: ReactNode;
}) {
  const [locale, setLocaleState] = useState<Locale>(initial);
  const setLocale = useCallback(
    (next: Locale) => {
      setLocaleState(next);
      setStoredLocale(next);
      if (root) root.dataset.locale = next;
    },
    [root],
  );
  const value = useMemo<LocaleState>(() => ({ locale, setLocale }), [locale, setLocale]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): Locale {
  return useContext(LocaleContext)?.locale ?? "en";
}

export function useT(): (key: TranslationKey) => string {
  const locale = useLocale();
  return useCallback((key: TranslationKey) => translate(key, locale), [locale]);
}

/** The pill that toggles between English and Simplified Chinese. */
export function LanguageSwitcher() {
  const { locale, setLocale } = useContext(LocaleContext) ?? { locale: "en" as Locale, setLocale: () => undefined };
  const isZh = locale === "zh-Hans";
  return (
    <button
      type="button"
      className="lc-lang-switch"
      aria-label="Switch language / 切换语言"
      onClick={() => setLocale(isZh ? "en" : "zh-Hans")}
    >
      <span className={isZh ? "lc-lang-opt" : "lc-lang-opt lc-lang-curr"}>EN</span>
      {" / "}
      <span className={isZh ? "lc-lang-opt lc-lang-curr" : "lc-lang-opt"}>中文</span>
    </button>
  );
}
