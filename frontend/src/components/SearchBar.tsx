import React, { useState } from 'react'
import { Search, Download, Loader2 } from 'lucide-react'
import { ingestPapers } from '../api'

interface Props {
  onSearch: (query: string) => void
  onIngestDone?: (count: number, query: string) => void
}

export default function SearchBar({ onSearch, onIngestDone }: Props) {
  const [query, setQuery] = useState('')
  const [ingesting, setIngesting] = useState(false)
  const [ingestMsg, setIngestMsg] = useState('')

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim()) onSearch(query.trim())
  }

  const handleIngest = async () => {
    if (!query.trim()) return
    setIngesting(true)
    setIngestMsg('')
    try {
      const res = await ingestPapers(query.trim(), 10)
      const msg = `Indexed ${res.papers_fetched} papers (${res.chunks_inserted} chunks)`
      setIngestMsg(msg)
      onIngestDone?.(res.papers_fetched, query.trim())
    } catch (err) {
      setIngestMsg(`Ingest failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setIngesting(false)
    }
  }

  return (
    <div className="w-full">
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 w-4 h-4" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search papers (e.g. RAG survey, attention mechanism...)"
            className="w-full pl-9 pr-4 py-2.5 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-purple-500 text-sm"
          />
        </div>
        <button
          type="submit"
          className="px-4 py-2.5 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-sm font-medium transition-colors"
        >
          Search
        </button>
        <button
          type="button"
          onClick={handleIngest}
          disabled={ingesting || !query.trim()}
          className="flex items-center gap-1.5 px-4 py-2.5 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
          title="Fetch papers from ArXiv and index into vector store"
        >
          {ingesting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Download className="w-4 h-4" />
          )}
          Index
        </button>
      </form>
      {ingestMsg && (
        <p className="mt-2 text-xs text-gray-400">{ingestMsg}</p>
      )}
    </div>
  )
}
