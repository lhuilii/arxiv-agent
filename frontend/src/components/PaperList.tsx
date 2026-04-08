import React, { useState } from 'react'
import { ExternalLink, Calendar, Users, Star, Trash2 } from 'lucide-react'
import { Paper } from '../types'

interface Props {
  papers: Paper[]
  favorites: Paper[]
  loading?: boolean
  onSelect?: (paper: Paper) => void
  onDelete?: (paperId: string) => void
  onToggleFavorite?: (paperId: string) => void
}

function PaperCard({
  paper,
  isFavorite,
  onSelect,
  onDelete,
  onToggleFavorite,
}: {
  paper: Paper
  isFavorite: boolean
  onSelect?: (p: Paper) => void
  onDelete?: (id: string) => void
  onToggleFavorite?: (id: string) => void
}) {
  return (
    <div
      className="group p-3 bg-gray-800 rounded-lg border border-gray-700 hover:border-purple-500 cursor-pointer transition-colors"
      onClick={() => onSelect?.(paper)}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium text-white leading-snug line-clamp-2 flex-1">
          {paper.title}
        </h3>
        <div className="flex items-center gap-0.5 flex-shrink-0">
          <button
            onClick={(e) => { e.stopPropagation(); onToggleFavorite?.(paper.paper_id) }}
            className={`p-1 rounded transition-colors ${
              isFavorite
                ? 'text-yellow-400 hover:text-yellow-300'
                : 'text-gray-600 hover:text-yellow-400 opacity-0 group-hover:opacity-100'
            }`}
            title={isFavorite ? '取消收藏' : '收藏'}
          >
            <Star className="w-3.5 h-3.5" fill={isFavorite ? 'currentColor' : 'none'} />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete?.(paper.paper_id) }}
            className="p-1 rounded text-gray-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
            title="从向量库删除"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
          <a
            href={paper.arxiv_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="p-1 rounded text-gray-400 hover:text-purple-400 transition-colors"
            title="在 ArXiv 中打开"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>
      </div>
      <div className="mt-1.5 flex items-center gap-3 text-xs text-gray-400">
        <span className="flex items-center gap-1 min-w-0">
          <Users className="w-3 h-3 flex-shrink-0" />
          <span className="truncate max-w-[120px]">{paper.authors}</span>
        </span>
        <span className="flex items-center gap-1 flex-shrink-0">
          <Calendar className="w-3 h-3" />
          {paper.published_date}
        </span>
      </div>
      {paper.score !== undefined && (
        <div className="mt-1.5 flex items-center gap-2">
          <div className="flex-1 h-1 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-purple-500 rounded-full"
              style={{ width: `${Math.round(paper.score * 100)}%` }}
            />
          </div>
          <span className="text-xs text-gray-500">{(paper.score * 100).toFixed(0)}%</span>
        </div>
      )}
    </div>
  )
}

export default function PaperList({ papers, favorites, loading, onSelect, onDelete, onToggleFavorite }: Props) {
  const [tab, setTab] = useState<'all' | 'favorites'>('all')

  const favoriteIds = new Set(favorites.map((p) => p.paper_id))
  const displayed = tab === 'favorites' ? favorites : papers

  return (
    <div className="flex flex-col h-full">
      {/* Tabs */}
      <div className="flex gap-1 mb-3">
        <button
          onClick={() => setTab('all')}
          className={`flex-1 text-xs py-1.5 rounded transition-colors font-medium ${
            tab === 'all' ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'
          }`}
        >
          全部{papers.length > 0 && ` (${papers.length})`}
        </button>
        <button
          onClick={() => setTab('favorites')}
          className={`flex-1 text-xs py-1.5 rounded transition-colors font-medium ${
            tab === 'favorites' ? 'bg-yellow-600 text-white' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'
          }`}
        >
          ★ 收藏{favorites.length > 0 && ` (${favorites.length})`}
        </button>
      </div>

      {/* Content */}
      {loading && tab === 'all' ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-20 bg-gray-800 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : displayed.length === 0 ? (
        <div className="text-center text-gray-500 text-sm py-8">
          {tab === 'favorites' ? '还没有收藏的论文' : 'No papers yet.\nSearch or ask the agent!'}
        </div>
      ) : (
        <div className="space-y-2">
          {displayed.map((p) => (
            <PaperCard
              key={p.paper_id}
              paper={p}
              isFavorite={favoriteIds.has(p.paper_id)}
              onSelect={onSelect}
              onDelete={onDelete}
              onToggleFavorite={onToggleFavorite}
            />
          ))}
        </div>
      )}
    </div>
  )
}
