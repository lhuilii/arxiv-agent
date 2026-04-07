import React, { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Send, Loader2, User, Bot } from 'lucide-react'
import { ChatMessage, ToolStep } from '../types'
import AgentTrace from './AgentTrace'
import { streamChat } from '../api'

interface Props {
  sessionId: string
  onPapersFound?: (paperIds: string[]) => void
}

export default function ChatPanel({ sessionId, onPapersFound }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = () => {
    const text = input.trim()
    if (!text || streaming) return

    setInput('')
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
    }

    const assistantId = crypto.randomUUID()
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      streaming: true,
      steps: [],
      timestamp: Date.now(),
    }

    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setStreaming(true)

    const steps: ToolStep[] = []

    abortRef.current = streamChat(
      text,
      sessionId,
      (event) => {
        if (event.type === 'token') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: m.content + (event.content as string) }
                : m,
            ),
          )
        } else if (event.type === 'tool_end') {
          steps.push({
            tool: event.tool as string,
            input: (event.input as string) ?? '',
            output: (event.output as string) ?? '',
          })
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, steps: [...steps] } : m,
            ),
          )
        } else if (event.type === 'final') {
          const finalSteps = (event.steps as ToolStep[]) ?? steps
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    content: (event.content as string) || m.content,
                    streaming: false,
                    steps: finalSteps,
                  }
                : m,
            ),
          )
        } else if (event.type === 'error') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: `Error: ${event.content}`, streaming: false }
                : m,
            ),
          )
        }
      },
      () => {
        setStreaming(false)
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, streaming: false } : m,
          ),
        )
      },
      (err) => {
        setStreaming(false)
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: `Connection error: ${err.message}`, streaming: false }
              : m,
          ),
        )
      },
    )
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const stopStreaming = () => {
    abortRef.current?.abort()
    setStreaming(false)
    setMessages((prev) =>
      prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 text-sm mt-8">
            <Bot className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p>Ask me anything about research papers!</p>
            <p className="text-xs mt-1 text-gray-600">
              Try: "Analyze the latest RAG papers" or "Compare attention mechanisms"
            </p>
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role === 'assistant' && (
              <div className="w-7 h-7 rounded-full bg-purple-700 flex items-center justify-center flex-shrink-0 mt-0.5">
                <Bot className="w-4 h-4 text-white" />
              </div>
            )}
            <div
              className={`max-w-[85%] ${
                msg.role === 'user'
                  ? 'bg-purple-600 text-white rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm'
                  : 'bg-gray-800 text-gray-100 rounded-2xl rounded-tl-sm px-4 py-3'
              }`}
            >
              {msg.role === 'assistant' ? (
                <>
                  <div className={`prose prose-invert prose-sm max-w-none ${msg.streaming && !msg.content ? 'cursor-blink' : ''}`}>
                    {msg.content ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {msg.content}
                      </ReactMarkdown>
                    ) : msg.streaming ? (
                      <span className="text-gray-400 text-xs italic">Thinking...</span>
                    ) : null}
                    {msg.streaming && msg.content && <span className="cursor-blink" />}
                  </div>
                  {msg.steps && <AgentTrace steps={msg.steps} />}
                </>
              ) : (
                <p>{msg.content}</p>
              )}
            </div>
            {msg.role === 'user' && (
              <div className="w-7 h-7 rounded-full bg-gray-600 flex items-center justify-center flex-shrink-0 mt-0.5">
                <User className="w-4 h-4 text-white" />
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-700 p-4">
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about papers... (Enter to send, Shift+Enter for newline)"
            rows={2}
            disabled={streaming}
            className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-purple-500 resize-none disabled:opacity-60"
          />
          {streaming ? (
            <button
              onClick={stopStreaming}
              className="p-2.5 bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors"
              title="Stop"
            >
              <Loader2 className="w-5 h-5 animate-spin" />
            </button>
          ) : (
            <button
              onClick={sendMessage}
              disabled={!input.trim()}
              className="p-2.5 bg-purple-600 hover:bg-purple-700 disabled:opacity-40 text-white rounded-lg transition-colors"
            >
              <Send className="w-5 h-5" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
