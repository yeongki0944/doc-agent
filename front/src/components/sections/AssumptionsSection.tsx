import { GenericSection } from './GenericSection'

export function AssumptionsSection() {
  return (
    <GenericSection
      title="Assumptions & Risks"
      sectionKey="assumptions"
      emptyMessage="가정 및 리스크가 아직 정의되지 않았습니다."
      chatHint="Assumptions 작성해줘"
    />
  )
}
