type TranslationMap = Record<string, string>

const zhCN: TranslationMap = {}
const enUS: TranslationMap = {}

const dictionaries: Record<string, TranslationMap> = {
  zh: zhCN,
  'zh-CN': zhCN,
  en: enUS,
  'en-US': enUS,
}

export type TranslationKey = string

export function getTranslation(language: string, key: TranslationKey): string {
  const target = dictionaries[language] || dictionaries.zh
  return target[key] || key
}
