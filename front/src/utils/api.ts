const API_BASE = import.meta.env.VITE_API_URL || 'https://7wejbdujd6.execute-api.ap-northeast-2.amazonaws.com'

export async function saveUserInput(docId: string, path: string, value: any): Promise<void> {
  await fetch(`${API_BASE}/documents/${docId}/user-input`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, value, edited_by: 'user' }),
  })
}

export async function getDocument(docId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/documents/${docId}`)
  if (!res.ok) throw new Error(`Failed to fetch document: ${res.status}`)
  return res.json()
}

export async function requestReview(docId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/documents/${docId}/review`, { method: 'POST' })
  return res.json()
}

export async function requestExport(docId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/documents/${docId}/export`, { method: 'POST' })
  return res.json()
}
