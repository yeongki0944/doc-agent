import { useState } from 'react'
import { color, radius, space } from '../../styles/tokens'

interface PocPreset {
  id: string
  label: string
  description: string
  sample_objectives: string[]
  aws_services: string[]
  prompt_hint: string
}

const POC_PRESETS: PocPreset[] = [
  {
    id: 'rag_chatbot',
    label: 'RAG Chatbot',
    description: '내부 문서 기반 Q&A 챗봇. Bedrock + OpenSearch + S3.',
    sample_objectives: [
      '문서 검색 정확도 80% 이상',
      '응답 latency P95 < 4초',
      '데이터 유출 방지를 위한 사내 망 배포',
    ],
    aws_services: ['Amazon Bedrock', 'Amazon OpenSearch Service', 'Amazon S3', 'AWS Lambda', 'Amazon API Gateway'],
    prompt_hint: 'RAG 기반 사내 문서 챗봇 PoC를 위한 Executive Summary, Scope, Architecture 초안을 작성해줘.',
  },
  {
    id: 'text_to_sql',
    label: 'Text-to-SQL',
    description: '자연어 → SQL 변환 및 사내 DB 조회 자동화.',
    sample_objectives: [
      '자연어 질의의 SQL 정확도 75% 이상',
      '비기술 사용자가 질의 가능',
      'DB 접근 권한 제어 및 감사 로그',
    ],
    aws_services: ['Amazon Bedrock', 'Amazon RDS', 'AWS Lambda', 'Amazon API Gateway', 'AWS IAM'],
    prompt_hint: 'Text-to-SQL 기반 DB 조회 어시스턴트 PoC를 위한 Executive Summary, Architecture, Scope 초안을 작성해줘.',
  },
  {
    id: 'ocr_document',
    label: 'OCR / Document Parser',
    description: '대량 문서 OCR 및 구조화 데이터 추출.',
    sample_objectives: [
      '주요 필드 추출 정확도 90% 이상',
      '시간당 처리량 1,000 페이지 이상',
      '수동 데이터 입력 공수 50% 절감',
    ],
    aws_services: ['Amazon Bedrock', 'Amazon Textract', 'Amazon S3', 'AWS Lambda', 'Amazon CloudWatch'],
    prompt_hint: 'OCR + LLM 기반 문서 파서 PoC를 위한 Executive Summary, Scope, Architecture 초안을 작성해줘.',
  },
  {
    id: 'recommendation_agent',
    label: 'Recommendation Agent',
    description: '사용자 행동/맥락 기반 개인화 추천.',
    sample_objectives: [
      '클릭률(CTR) 20% 이상 개선',
      '실시간 추천 latency < 300ms',
      '콜드 스타트 사용자 처리',
    ],
    aws_services: ['Amazon Bedrock', 'Amazon SageMaker', 'Amazon OpenSearch Service', 'AWS Lambda', 'Amazon EventBridge'],
    prompt_hint: '개인화 추천 에이전트 PoC를 위한 Executive Summary, Scope, Architecture 초안을 작성해줘.',
  },
  {
    id: 'ai_governance',
    label: 'AI Governance',
    description: 'LLM 사용 모니터링, guardrail, policy enforcement.',
    sample_objectives: [
      'PII 탐지 및 마스킹 정책 적용',
      '모든 LLM 호출 감사 로그 저장',
      '프롬프트 인젝션 탐지율 90% 이상',
    ],
    aws_services: ['Amazon Bedrock Guardrails', 'AWS CloudTrail', 'Amazon CloudWatch', 'AWS KMS', 'AWS WAF'],
    prompt_hint: 'AI Governance 플랫폼 PoC를 위한 Executive Summary, Scope, Architecture, Assumptions 초안을 작성해줘.',
  },
  {
    id: 'customer_support',
    label: 'Customer Support Automation',
    description: '상담 이력/FAQ 기반 자동 응답 및 티켓 분류.',
    sample_objectives: [
      '1차 응답 자동화율 60% 이상',
      '티켓 분류 정확도 85% 이상',
      '상담사 핸드오프 플로우 검증',
    ],
    aws_services: ['Amazon Bedrock', 'Amazon Connect', 'Amazon OpenSearch Service', 'AWS Lambda', 'Amazon DynamoDB'],
    prompt_hint: '고객 상담 자동화 PoC를 위한 Executive Summary, Scope, Architecture 초안을 작성해줘.',
  },
]

/**
 * Section Preset / Dropdown Recommendation Panel — shows static PoC type
 * presets. Users can copy an AI prompt hint to chat or see suggested AWS
 * services. Applying to document directly is deferred to the chat flow to
 * avoid unexpected mutations while the backend recommendation API matures.
 */
export function SectionSuggestionsPanel({
  activeTab,
  onSendPrompt,
}: {
  activeTab: string
  onSendPrompt?: (prompt: string) => void
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  const selected = POC_PRESETS.find(p => p.id === selectedId) || null

  const handleCopy = async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(id)
      setTimeout(() => setCopied(null), 1500)
    } catch {
      setCopied(null)
    }
  }

  return (
    <div style={{ padding: space.md, display: 'flex', flexDirection: 'column', gap: space.md }}>
      <div>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Section Suggestions</h3>
        <div style={{ fontSize: 11, color: color.textMuted, marginTop: 2 }}>
          현재 섹션: <span style={{ fontWeight: 500 }}>{activeTab}</span>
        </div>
      </div>

      <div style={{ fontSize: 11, color: color.textMuted, padding: space.sm, background: color.bgSubtle, borderRadius: radius.sm, lineHeight: 1.5 }}>
        PoC 유형을 선택하면 권장 AWS 서비스, 샘플 목표, AI 프롬프트 힌트를 볼 수 있습니다. 프롬프트를 복사해 왼쪽 채팅에 붙여넣으세요.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        {POC_PRESETS.map(preset => (
          <button
            key={preset.id}
            onClick={() => setSelectedId(preset.id === selectedId ? null : preset.id)}
            style={{
              padding: 8,
              textAlign: 'left',
              borderRadius: radius.sm,
              border: `1px solid ${selectedId === preset.id ? color.mzRed : color.border}`,
              background: selectedId === preset.id ? '#fef2f2' : color.bgSurface,
              cursor: 'pointer',
              fontSize: 12,
              fontWeight: 600,
              color: selectedId === preset.id ? color.mzRed : color.textPrimary,
            }}
          >
            {preset.label}
          </button>
        ))}
      </div>

      {selected && <PresetDetail preset={selected} copied={copied} onCopy={handleCopy} onSendPrompt={onSendPrompt} />}
    </div>
  )
}

function PresetDetail({
  preset,
  copied,
  onCopy,
  onSendPrompt,
}: {
  preset: PocPreset
  copied: string | null
  onCopy: (text: string, id: string) => void
  onSendPrompt?: (prompt: string) => void
}) {
  return (
    <div style={{
      padding: space.sm,
      border: `1px solid ${color.border}`,
      borderRadius: radius.sm,
      background: color.bgSurface,
      display: 'flex',
      flexDirection: 'column',
      gap: space.sm,
    }}>
      <div style={{ fontSize: 12, color: color.textSecondary, lineHeight: 1.5 }}>
        {preset.description}
      </div>

      <div>
        <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>권장 AWS 서비스</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {preset.aws_services.map(s => (
            <span key={s} style={{
              padding: '2px 6px', fontSize: 10, borderRadius: 4,
              border: `1px solid ${color.border}`, background: color.bgSubtle, color: color.textSecondary,
            }}>{s}</span>
          ))}
        </div>
      </div>

      <div>
        <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>샘플 PoC 목표</div>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 11, color: color.textSecondary, lineHeight: 1.6 }}>
          {preset.sample_objectives.map((o, i) => <li key={i}>{o}</li>)}
        </ul>
      </div>

      <div>
        <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>AI 프롬프트 힌트</div>
        <div style={{
          padding: 8, fontSize: 11, background: color.bgSubtle, borderRadius: radius.sm,
          color: color.textSecondary, lineHeight: 1.5, fontFamily: 'monospace',
          whiteSpace: 'pre-wrap',
        }}>
          {preset.prompt_hint}
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          <button
            onClick={() => onCopy(preset.prompt_hint, preset.id)}
            style={{
              padding: '4px 10px', fontSize: 11, borderRadius: radius.sm,
              border: `1px solid ${color.border}`, background: color.bgSurface,
              color: color.textSecondary, cursor: 'pointer',
            }}
          >
            {copied === preset.id ? '✓ 복사됨' : '프롬프트 복사'}
          </button>
          {onSendPrompt && (
            <button
              onClick={() => onSendPrompt(preset.prompt_hint)}
              style={{
                padding: '4px 10px', fontSize: 11, borderRadius: radius.sm,
                border: 'none', background: color.mzRed, color: color.bgSurface,
                fontWeight: 600, cursor: 'pointer',
              }}
            >
              채팅으로 보내기
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export { POC_PRESETS }
