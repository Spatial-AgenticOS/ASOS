import React from 'react';
import { Mic } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { SduiRenderer } from '../SduiRenderer';
import TheOrb from '../TheOrb';
import SkillProposalCard from './SkillProposalCard';

function MessageActions({ text, onRetry }) {
  return (
    <div style={{ display: 'flex', gap: '4px', opacity: 0.3, transition: 'opacity 0.15s' }}
         className="message-actions">
      <button onClick={() => navigator.clipboard.writeText(text)} title="Copy"
        style={{ background: 'none', border: 'none', color: '#71717a', cursor: 'pointer', padding: '4px' }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
      </button>
      {onRetry && (
        <button onClick={onRetry} title="Retry"
          style={{ background: 'none', border: 'none', color: '#71717a', cursor: 'pointer', padding: '4px' }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 4v6h6"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg>
        </button>
      )}
    </div>
  );
}

export default function MessageList({
  messages, isConnected, isStreaming, streamingText, isThinking,
  greeting, onQuickAction, onUIAction, onSkillDecision, skillProposalBusy,
  messagesEndRef,
}) {
  const getRetryHandler = (idx) => {
    const prev = messages.slice(0, idx).reverse().find(m => m.role === 'user' && m.type === 'text');
    return prev ? () => onQuickAction(prev.content) : null;
  };

  return (
    <div className="flex-1 overflow-y-auto px-3 lg:px-5 py-4 space-y-2.5">
      {messages.length === 0 && (
        <div className="flex flex-col items-center justify-center h-full gap-4 px-6">
          <TheOrb size={56} mode={isConnected ? 'idle' : 'disconnected'} connected={isConnected} />
          <div className="text-center space-y-1">
            <p className="text-base font-medium text-feral-text">
              {greeting?.greeting || (new Date().getHours() < 12 ? 'Good morning.' : new Date().getHours() < 18 ? 'Good afternoon.' : 'Good evening.')}
            </p>
            {greeting?.health_summary && (
              <p className="text-xs text-feral-text-secondary">{greeting.health_summary}</p>
            )}
            {!greeting?.health_summary && (
              <p className="text-xs text-feral-text-muted">Type a message, use voice, or press <kbd className="text-[10px] bg-feral-card px-1 py-0.5 rounded border border-feral-border font-mono">⌘K</kbd></p>
            )}
          </div>
          <div className="flex flex-wrap justify-center gap-2 mt-1">
            {[
              { label: 'Start briefing', text: 'Give me my morning briefing' },
              { label: 'Check health', text: 'How is my health right now?' },
              { label: 'What was I working on?', text: 'What was I working on recently?' },
            ].map(action => (
              <button
                key={action.label}
                onClick={() => onQuickAction(action.text)}
                className="text-xs px-3 py-1.5 rounded-full border border-feral-border text-feral-text-secondary hover:text-feral-accent hover:border-feral-accent/30 hover:bg-feral-accent-dim transition"
              >
                {action.label}
              </button>
            ))}
          </div>
          {greeting?.last_memory && (
            <p className="text-[11px] text-feral-text-muted mt-2 max-w-sm text-center italic">
              Yesterday: &quot;{greeting.last_memory}&quot;
            </p>
          )}
        </div>
      )}
      {messages.map((msg, idx) => (
        <div key={idx} className={`msg-enter flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`} style={{ animationDelay: `${Math.min(idx * 30, 150)}ms` }}>
          {msg.role === 'user' ? (
            <div className="max-w-[78%] bg-feral-user text-white rounded-2xl rounded-br-sm px-3.5 py-2 shadow-md shadow-feral-user/10">
              {msg.type === 'text' && (
                <span className="text-[13px] leading-snug">
                  {msg.source === 'voice' && <Mic size={11} className="inline mr-1 opacity-60" />}
                  {msg.content}
                </span>
              )}
              {msg.type === 'action' && <span className="text-[11px] italic opacity-80">{msg.content}</span>}
            </div>
          ) : msg.role === 'system' ? (
            <div className="w-full flex justify-center">
              <span className="text-[10px] text-feral-text-muted bg-feral-card px-2.5 py-0.5 rounded-full border border-feral-border">{msg.content}</span>
            </div>
          ) : (
            <div className="flex gap-2 max-w-[80%]">
              <div className="flex-shrink-0 mt-1">
                <TheOrb size={14} mode={msg.type === 'stream_delta' ? 'thinking' : 'idle'} connected={isConnected} />
              </div>
              <div className="min-w-0">
                {msg.type === 'text' && (
                  <div className="msg-bubble bg-feral-assistant border border-feral-border rounded-2xl rounded-bl-sm px-3.5 py-2">
                    {msg.source === 'voice' && <Mic size={11} className="inline mr-1 text-feral-text-muted" />}
                    <div className="markdown-body text-[13px] leading-snug text-feral-text">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                    <MessageActions text={msg.content} onRetry={getRetryHandler(idx)} />
                  </div>
                )}
                {msg.type === 'tool_start' && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', background: 'rgba(6,182,212,0.1)', borderRadius: '8px', fontSize: '13px', color: '#06b6d4' }}>
                    <span className="animate-spin" style={{ width: 14, height: 14, border: '2px solid currentColor', borderTopColor: 'transparent', borderRadius: '50%', display: 'inline-block' }} />
                    Running {msg.payload?.tool_name || 'tool'}...
                  </div>
                )}
                {msg.type === 'sdui' && (
                  <div className="sdui-fade-in rounded-xl overflow-hidden">
                    <SduiRenderer node={msg.payload} onAction={onUIAction} compact />
                  </div>
                )}
                {msg.type === 'skill_proposal' && (
                  <SkillProposalCard
                    msg={msg}
                    onDecision={onSkillDecision}
                    busy={skillProposalBusy}
                  />
                )}
              </div>
            </div>
          )}
        </div>
      ))}
      {isStreaming && streamingText && (
        <div className="flex justify-start">
          <div className="flex gap-2 max-w-[80%]">
            <div className="flex-shrink-0 mt-1"><TheOrb size={14} mode="speaking" connected /></div>
            <div className="bg-feral-assistant border border-feral-border rounded-2xl rounded-bl-sm px-3.5 py-2">
              <div className="markdown-body text-[13px] leading-snug text-feral-text">
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                  {streamingText}
                </ReactMarkdown>
              </div>
              <span className="inline-block w-1 h-3.5 bg-feral-accent rounded-sm animate-pulse ml-0.5 align-middle" />
            </div>
          </div>
        </div>
      )}
      {isThinking && !isStreaming && (
        <div className="flex justify-start">
          <div className="flex gap-2">
            <div className="flex-shrink-0 mt-1"><TheOrb size={14} mode="thinking" connected /></div>
            <div className="flex items-center gap-1.5 px-3.5 py-2.5 bg-feral-assistant border border-feral-border rounded-2xl rounded-bl-sm">
              <span className="thinking-dot" style={{ animationDelay: '0ms' }} />
              <span className="thinking-dot" style={{ animationDelay: '200ms' }} />
              <span className="thinking-dot" style={{ animationDelay: '400ms' }} />
            </div>
          </div>
        </div>
      )}
      <div ref={messagesEndRef} />
    </div>
  );
}
