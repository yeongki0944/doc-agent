import { GenericSection } from './GenericSection'

export function AcceptanceSection() {
  return (
    <GenericSection
      title="Acceptance Criteria"
      sectionKey="acceptance"
      emptyMessage="인수 기준이 아직 정의되지 않았습니다."
      chatHint="Acceptance Criteria 작성해줘"
    />
  )
}
