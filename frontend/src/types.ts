// Shared types for the ArXiv Agent frontend

export interface Paper {
  paper_id: string
  title: string
  authors: string
  abstract?: string
  published_date: string
  arxiv_url: string
  score?: number
  source?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  steps?: ToolStep[]
  traceUrl?: string
  timestamp: number
}

export interface ToolStep {
  tool: string
  input: string
  output: string
}

export type SSEEvent =
  | { type: 'token'; content: string }
  | { type: 'tool_start'; tool: string; input: string }
  | { type: 'tool_end'; tool: string; output: string }
  | { type: 'final'; content: string; steps: ToolStep[] }
  | { type: 'error'; content: string }
