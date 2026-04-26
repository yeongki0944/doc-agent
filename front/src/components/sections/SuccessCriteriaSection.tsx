import { GenericSection } from './GenericSection'

export function SuccessCriteriaSection() {
  return (
    <GenericSection
      title="Success Criteria / KPIs"
      sectionKey="success_criteria"
      emptyMessage="성공 기준이 아직 정의되지 않았습니다."
      chatHint="Success Criteria 작성해줘"
    />
  )
}
