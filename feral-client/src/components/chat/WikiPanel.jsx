import React from 'react';
import { BookOpen, RefreshCw, Search } from 'lucide-react';

export default function WikiPanel({
  wikiPages, wikiQuery, setWikiQuery, wikiLoading, wikiSelected,
  wikiIngestOpen, setWikiIngestOpen,
  wikiIngestType, setWikiIngestType,
  wikiIngestPath, setWikiIngestPath,
  wikiIngestContent, setWikiIngestContent,
  wikiIngestBusy, wikiIngestResult,
  fetchWikiPages, compileWiki, ingestWiki, openWikiPage,
}) {
  return (
    <div className="absolute inset-0 z-20 bg-feral-bg/95 backdrop-blur-md flex flex-col">
      <div className="pt-16 px-4 pb-3 border-b border-feral-border">
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-2">
            <BookOpen size={16} className="text-feral-accent" />
            <span className="text-sm font-semibold">Memory Wiki</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setWikiIngestOpen(v => !v)}
              className={`text-xs px-2 py-1 rounded border flex items-center gap-1 ${
                wikiIngestOpen
                  ? 'bg-feral-accent/20 border-feral-accent text-feral-accent'
                  : 'bg-feral-card border-feral-border hover:border-feral-accent'
              }`}
            >
              Ingest
            </button>
            <button
              onClick={compileWiki}
              className="text-xs px-2 py-1 rounded bg-feral-card border border-feral-border hover:border-feral-accent flex items-center gap-1"
              disabled={wikiLoading}
            >
              <RefreshCw size={12} className={wikiLoading ? 'animate-spin' : ''} />
              Compile
            </button>
          </div>
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={wikiQuery}
            onChange={(e) => setWikiQuery(e.target.value)}
            placeholder="Search wiki pages..."
            className="flex-1 bg-feral-card border border-feral-border rounded-full px-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-feral-accent"
          />
          <button
            onClick={() => fetchWikiPages(wikiQuery)}
            className="px-3 py-2 rounded-full bg-feral-card border border-feral-border hover:border-feral-accent"
          >
            <Search size={14} />
          </button>
        </div>
        {wikiIngestOpen && (
          <div className="mt-3 p-3 bg-feral-card border border-feral-border rounded-xl space-y-2">
            <div className="flex gap-2">
              <select
                value={wikiIngestType}
                onChange={(e) => setWikiIngestType(e.target.value)}
                className="bg-feral-bg border border-feral-border rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-feral-accent"
              >
                <option value="repo">Repo</option>
                <option value="pdf">PDF</option>
                <option value="text">Text</option>
              </select>
              {(wikiIngestType === 'repo' || wikiIngestType === 'pdf') && (
                <input
                  type="text"
                  value={wikiIngestPath}
                  onChange={(e) => setWikiIngestPath(e.target.value)}
                  placeholder={wikiIngestType === 'repo' ? '/path/to/repo' : '/path/to/file.pdf'}
                  className="flex-1 bg-feral-bg border border-feral-border rounded-lg px-3 py-2 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-feral-accent"
                />
              )}
            </div>
            {wikiIngestType === 'text' && (
              <textarea
                rows={4}
                value={wikiIngestContent}
                onChange={(e) => setWikiIngestContent(e.target.value)}
                placeholder="Paste text to ingest into memory wiki..."
                className="w-full bg-feral-bg border border-feral-border rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-feral-accent resize-y"
              />
            )}
            <div className="flex items-center justify-between">
              <button
                onClick={ingestWiki}
                disabled={wikiIngestBusy}
                className="text-xs px-3 py-1.5 rounded bg-feral-accent text-white hover:bg-feral-accent/90 disabled:opacity-60"
              >
                {wikiIngestBusy ? 'Ingesting...' : 'Run Ingest'}
              </button>
              {wikiIngestResult && <span className="text-[11px] text-feral-text-secondary">{wikiIngestResult}</span>}
            </div>
          </div>
        )}
      </div>

      <div className="flex-1 grid grid-cols-1 md:grid-cols-2 overflow-hidden">
        <div className="border-r border-feral-border overflow-y-auto">
          {wikiPages.map((page) => (
            <button
              key={page.id}
              onClick={() => openWikiPage(page.id)}
              className={`w-full text-left px-4 py-3 border-b border-feral-border/40 hover:bg-feral-card ${
                wikiSelected?.id === page.id ? 'bg-feral-card' : ''
              }`}
            >
              <div className="text-sm font-medium">{page.title}</div>
              <div className="text-xs opacity-60">{page.kind} • {page.id}</div>
            </button>
          ))}
          {!wikiPages.length && !wikiLoading && (
            <div className="p-4 text-sm opacity-60">No wiki pages yet. Press Compile.</div>
          )}
        </div>
        <div className="overflow-y-auto p-4">
          {wikiSelected ? (
            <div className="space-y-3">
              <div className="text-lg font-semibold">{wikiSelected.title}</div>
              <div className="text-xs opacity-60">{wikiSelected.kind} • {wikiSelected.id}</div>
              <pre className="whitespace-pre-wrap text-sm leading-relaxed bg-feral-card border border-feral-border rounded-xl p-3">
                {wikiSelected.body_markdown}
              </pre>
            </div>
          ) : (
            <div className="text-sm opacity-60">Select a wiki page to view details.</div>
          )}
        </div>
      </div>
    </div>
  );
}
