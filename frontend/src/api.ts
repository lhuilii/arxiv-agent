const BASE = '/api'

export async function ingestPapers(query: string, limit = 10, parsePdf = false) {
  const res = await fetch(`${BASE}/papers/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, limit, parse_pdf: parsePdf }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function searchPapers(q: string, topK = 5) {
  const res = await fetch(`${BASE}/papers/search?q=${encodeURIComponent(q)}&top_k=${topK}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getSessionHistory(sessionId: string) {
  const res = await fetch(`${BASE}/session/${sessionId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function clearCache() {
  const res = await fetch(`${BASE}/cache`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function healthCheck() {
  const res = await fetch(`${BASE}/health`)
  return res.json()
}

/**
 * Stream agent chat via SSE.
 * Calls onEvent for each parsed SSE data event.
 */
export function streamChat(
  message: string,
  sessionId: string,
  onEvent: (event: { type: string; [key: string]: unknown }) => void,
  onDone: () => void,
  onError: (err: Error) => void,
): AbortController {
  const controller = new AbortController()

  fetch(`${BASE}/agent/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      if (!res.body) throw new Error('No response body')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              onEvent(data)
            } catch {
              // ignore malformed lines
            }
          }
        }
      }
      onDone()
    })
    .catch((err) => {
      if (err.name !== 'AbortError') onError(err)
    })

  return controller
}
