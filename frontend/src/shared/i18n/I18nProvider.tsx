import { createContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { en } from "./locales/en";
import { zhCN, type LocaleDictionary } from "./locales/zh-CN";

export type Locale = "zh-CN" | "en";

const LOCALE_STORAGE_KEY = "memwing.locale";

const dictionaries: Record<Locale, LocaleDictionary> = {
  "zh-CN": zhCN,
  en,
};

export type I18nContextValue = {
  locale: Locale;
  dictionary: LocaleDictionary;
  setLocale: (locale: Locale) => void;
};

export const I18nContext = createContext<I18nContextValue | null>(null);

function readInitialLocale(): Locale {
  if (typeof window === "undefined") {
    return "zh-CN";
  }

  const storedLocale = window.localStorage.getItem(LOCALE_STORAGE_KEY);
  return storedLocale === "en" || storedLocale === "zh-CN" ? storedLocale : "zh-CN";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readInitialLocale);

  useEffect(() => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo<I18nContextValue>(() => ({
    locale,
    dictionary: dictionaries[locale],
    setLocale: setLocaleState,
  }), [locale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
