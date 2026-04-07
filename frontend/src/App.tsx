import React, { useEffect, useRef, useState } from 'react'
import { BookOpen, Cpu, Database, Wifi, WifiOff } from 'lucide-react'
import SearchBar from './components/SearchBar'
import PaperList from './components/PaperList'
import ChatPanel from './components/ChatPanel'
import { Paper } from './types'
import { searchPapers, healthCheck } from './api'

const SESSION_ID = crypto.randomUUID()

export default function App() {
  const [papers, setPapers] = useState<Paper[]>([])
  const [loadingPapers, setLoadingPapers] = useState(false)
  const [health, setHealth] = useState<{ status: string; services?: Record<string, string> } | null>(null)

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

  const handleIngestDone = async () => {
    // Refresh papers list after ingestion
  }

  const serviceOk = health?.status === 'ok'

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col">
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
          <div className="px-4 py-2.5 border-b border-gray-800">
            <h2 className="text-sm font-medium text-gray-300">
              Papers
              {papers.length > 0 && (
                <span className="ml-2 text-xs text-gray-500">({papers.length})</span>
              )}
            </h2>
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            <PaperList
              papers={papers}
              loading={loadingPapers}
              onSelect={(p) => window.open(p.arxiv_url, '_blank')}
            />
          </div>
        </aside>

        {/* Right panel: Chat */}
        <main className="flex-1 flex flex-col min-w-0">
          <ChatPanel sessionId={SESSION_ID} />
        </main>
      </div>
    </div>
  )
}
