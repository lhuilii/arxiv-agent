import React from 'react'
import { ExternalLink, Calendar, Users } from 'lucide-react'
import { Paper } from '../types'

interface Props {
  papers: Paper[]
  loading?: boolean
  onSelect?: (paper: Paper) => void
}

function PaperCard({ paper, onSelect }: { paper: Paper; onSelect?: (p: Paper) => void }) {
  return (
    <div
      className="p-3 bg-gray-800 rounded-lg border border-gray-700 hover:border-purple-500 cursor-pointer transition-colors"
      onClick={() => onSelect?.(paper)}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium text-white leading-snug line-clamp-2 flex-1">
          {paper.title}
        </h3>
        <a
          href={paper.arxiv_url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="flex-shrink-0 text-gray-400 hover:text-purple-400 transition-colors"
        >
          <ExternalLink className="w-3.5 h-3.5" />
        </a>
      </div>
      <div className="mt-1.5 flex items-center gap-3 text-xs text-gray-400">
        <span className="flex items-center gap-1">
          <Users className="w-3 h-3" />
          <span className="truncate max-w-[120px]">{paper.authors}</span>
        </span>
        <span className="flex items-center gap-1">
          <Calendar className="w-3 h-3" />
          {paper.published_date}
        </span>
      </div>
      {paper.score !== undefined && (
        <div className="mt-1.5">
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1 bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-purple-500 rounded-full"
                style={{ width: `${Math.round(paper.score * 100)}%` }}
              />
            </div>
            <span className="text-xs text-gray-500">{(paper.score * 100).toFixed(0)}%</span>
          </div>
        </div>
      )}
    </div>
  )
}

export default function PaperList({ papers, loading, onSelect }: Props) {
  if (loading) {
    return (
      <div className="space-y-2">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-20 bg-gray-800 rounded-lg animate-pulse" />
        ))}
      </div>
    )
  }

  if (papers.length === 0) {
    return (
      <div className="text-center text-gray-500 text-sm py-8">
        No papers yet. Search or ask the agent!
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {papers.map((p) => (
        <PaperCard key={p.paper_id} paper={p} onSelect={onSelect} />
      ))}
    </div>
  )
}
