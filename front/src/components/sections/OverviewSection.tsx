import { GenericSection } from './GenericSection'

export function OverviewSection() {
  return (
    <GenericSection
      title="Executive Summary"
      sectionKey="executive_summary"
      emptyMessage="프로젝트 개요가 아직 입력되지 않았습니다."
      chatHint="Overview 작성해줘"
    />
  )
}
