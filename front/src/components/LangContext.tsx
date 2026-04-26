import { createContext, useContext } from 'react'

export type DocLang = 'ko' | 'en'

const LangContext = createContext<DocLang>('ko')

export const LangProvider = LangContext.Provider

export function useDocLang(): DocLang {
  return useContext(LangContext)
}
