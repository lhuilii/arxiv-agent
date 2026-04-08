import React, { useEffect, useState } from 'react'
import { BookOpen, Cpu, Database, Wifi, WifiOff } from 'lucide-react'
import SearchBar from './components/SearchBar'
import PaperList from './components/PaperList'
import ChatPanel from './components/ChatPanel'
import { Paper } from './types'
import { searchPapers, healthCheck, deletePaper } from './api'

const SESSION_ID = crypto.randomUUID()

export default function App() {
  const [papers, setPapers] = useState<Paper[]>([])
  const [loadingPapers, setLoadingPapers] = useState(false)
  const [health, setHealth] = useState<{ status: string; services?: Record<string, string> } | null>(null)
  const [favorites, setFavorites] = useState<Paper[]>(() => {
    try {
      const stored = localStorage.getItem('arxiv-favorites')
      return stored ? JSON.parse(stored) : []
    } catch {
      return []
    }
  })

  useEffect(() => {
    healthCheck().then(setHealth).catch(() => setHealth({ status: 'unreachable' }))
  }, [])

  const handleSearch = async (query: string) => {
    setLoadingPapers(true)
    try {
      const data = await searchPapers(query, 10)
      setPapers(data.results ?? [])
    } catch (err) {
      console.error('Search failed:', err)
      setPapers([])
    } finally {
      setLoadingPapers(false)
    }
  }

  const handleIngestDone = (_count: number, query: string) => {
    if (query) handleSearch(query)
  }

  const handleToggleFavorite = (paperId: string) => {
    setFavorites((prev) => {
      const exists = prev.some((p) => p.paper_id === paperId)
      const next = exists
        ? prev.filter((p) => p.paper_id !== paperId)
        : (() => {
            const paper = papers.find((p) => p.paper_id === paperId)
            return paper ? [...prev, paper] : prev
          })()
      localStorage.setItem('arxiv-favorites', JSON.stringify(next))
      return next
    })
  }

  const handleDeletePaper = async (paperId: string) => {
    // Optimistic update: remove from UI immediately
    setPapers((prev) => prev.filter((p) => p.paper_id !== paperId))
    setFavorites((prev) => {
      const next = prev.filter((p) => p.paper_id !== paperId)
      if (next.length !== prev.length) {
        localStorage.setItem('arxiv-favorites', JSON.stringify(next))
      }
      return next
    })
    // Delete from Milvus in background
    try {
      await deletePaper(paperId)
    } catch (err) {
      console.error('Delete from Milvus failed:', err)
    }
  }

  const serviceOk = health?.status === 'ok'

  return (
    <div className="h-screen bg-gray-950 text-white flex flex-col overflow-hidden">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <BookOpen className="w-6 h-6 text-purple-400" />
          <h1 className="text-lg font-semibold">ArXiv Research Agent</h1>
          <span className="text-xs bg-purple-900 text-purple-300 px-2 py-0.5 rounded-full">Beta</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          <div className="flex items-center gap-1.5">
            <Cpu className="w-3.5 h-3.5" />
            <span>Qwen Plus</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Database className="w-3.5 h-3.5" />
            <span>Milvus + Redis</span>
          </div>
          <div className={`flex items-center gap-1 ${serviceOk ? 'text-green-400' : 'text-red-400'}`}>
            {serviceOk ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
            <span>{health?.status ?? 'connecting...'}</span>
          </div>
        </div>
      </header>

      {/* Search Bar */}
      <div className="px-6 py-3 border-b border-gray-800">
        <SearchBar onSearch={handleSearch} onIngestDone={handleIngestDone} />
      </div>

      {/* Main layout: Papers list (left) + Chat panel (right) */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left panel: Paper list */}
        <aside className="w-80 flex-shrink-0 border-r border-gray-800 flex flex-col">
          <div className="flex-1 overflow-y-auto p-3">
            <PaperList
              papers={papers}
              favorites={favorites}
              loading={loadingPapers}
              onSelect={(p) => window.open(p.arxiv_url, '_blank')}
              onDelete={handleDeletePaper}
              onToggleFavorite={handleToggleFavorite}
            />
          </div>
        </aside>

        {/* Right panel: Chat */}
        <main className="flex-1 flex flex-col min-w-0">
          <ChatPanel sessionId={SESSION_ID} onQuerySearch={handleSearch} />
        </main>
      </div>
    </div>
  )
}
