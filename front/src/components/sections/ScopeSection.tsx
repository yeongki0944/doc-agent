import { GenericSection } from './GenericSection'

export function ScopeSection() {
  return (
    <GenericSection
      title="Scope of Work"
      sectionKey="scope_of_work"
      emptyMessage="프로젝트 범위가 아직 정의되지 않았습니다."
      chatHint="Scope 작성해줘"
    />
  )
}
