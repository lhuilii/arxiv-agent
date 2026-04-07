import React from 'react'
import { ChevronDown, ChevronRight, Wrench } from 'lucide-react'
import { ToolStep } from '../types'

interface Props {
  steps: ToolStep[]
  traceUrl?: string
}

const TOOL_COLORS: Record<string, string> = {
  search_papers: 'bg-blue-900 text-blue-300 border-blue-700',
  get_paper_detail: 'bg-green-900 text-green-300 border-green-700',
  analyze_paper: 'bg-yellow-900 text-yellow-300 border-yellow-700',
  compare_papers: 'bg-orange-900 text-orange-300 border-orange-700',
  generate_report: 'bg-purple-900 text-purple-300 border-purple-700',
}

function ToolCallItem({ step }: { step: ToolStep }) {
  const [open, setOpen] = React.useState(false)
  const colorClass = TOOL_COLORS[step.tool] ?? 'bg-gray-800 text-gray-300 border-gray-700'

  return (
    <div className={`border rounded-lg overflow-hidden ${colorClass}`}>
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
        onClick={() => setOpen(!open)}
      >
        <Wrench className="w-3.5 h-3.5 flex-shrink-0" />
        <span className="text-xs font-mono font-medium flex-1">{step.tool}</span>
        {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 bg-black/20">
          <div>
            <p className="text-xs text-gray-400 mb-1">Input:</p>
            <pre className="text-xs whitespace-pre-wrap break-words text-gray-300 max-h-32 overflow-y-auto">
              {step.input}
            </pre>
          </div>
          <div>
            <p className="text-xs text-gray-400 mb-1">Output:</p>
            <pre className="text-xs whitespace-pre-wrap break-words text-gray-300 max-h-40 overflow-y-auto">
              {step.output}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}

export default function AgentTrace({ steps, traceUrl }: Props) {
  const [visible, setVisible] = React.useState(false)

  if (steps.length === 0) return null

  return (
    <div className="mt-2">
      <button
        className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-200 transition-colors"
        onClick={() => setVisible(!visible)}
      >
        {visible ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <Wrench className="w-3 h-3" />
        {steps.length} tool call{steps.length > 1 ? 's' : ''}
        {traceUrl && (
          <a
            href={traceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-2 text-purple-400 hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            LangSmith trace
          </a>
        )}
      </button>
      {visible && (
        <div className="mt-2 space-y-1.5">
          {steps.map((step, i) => (
            <ToolCallItem key={i} step={step} />
          ))}
        </div>
      )}
    </div>
  )
}
