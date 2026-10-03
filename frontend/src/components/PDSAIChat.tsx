import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../services/api'
import type { AIAssistantAccess, AIChatMessage } from '../types'
import { Cross, Send, Sparkles, Spinner } from './Icons'

const EXAMPLES = [
  'How many releases happened this month?',
  'Show failed deployments last month.',
  'Who is the Release Manager for PDS-001?',
  'What is the Change No. for PDS-001?',
  'How many tenants are configured?',
]

export function PDSAIChat() {
  const [access, setAccess] = useState<AIAssistantAccess | null>(null)
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<AIChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [queryStatus, setQueryStatus] = useState('')
  const [queryPeriod, setQueryPeriod] = useState('this month')
  const [guidanceOpen, setGuidanceOpen] = useState(true)
  const endRef = useRef<HTMLDivElement | null>(null)

  const refreshAccess = useCallback(() => {
    api.getAIAssistantAccess().then(setAccess).catch(() => setAccess(null))
  }, [])

  useEffect(() => {
    refreshAccess()
    window.addEventListener('pds-ai-access-changed', refreshAccess)
    return () => window.removeEventListener('pds-ai-access-changed', refreshAccess)
  }, [refreshAccess])

  useEffect(() => {
    if (access && !access.allowed) setOpen(false)
  }, [access])

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy, open])

  async function send(text = input) {
    const question = text.trim()
    if (!question || busy || !access?.chat_configured) return
    const history = messages.slice(-10)
    setMessages((current) => [...current, { role: 'user', content: question }])
    setInput('')
    setError('')
    setBusy(true)
    setGuidanceOpen(false)
    try {
      const result = await api.chatPDSAI(question, history)
      setMessages((current) => [...current, { role: 'assistant', content: result.answer }])
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'PDS AI could not answer this question.')
    } finally {
      setBusy(false)
    }
  }

  if (!access?.allowed) return null

  const builtIn = ['builtin', 'built_in', 'rules', 'rule_based', 'local_rules'].includes(access.provider)
  const assistantTitle = builtIn ? 'PDS Assistant' : 'PDS AI Assistant'
  const askLabel = builtIn ? 'Ask PDS' : 'Ask PDS AI'

  return (
    <>
      {open ? (
        <section
          aria-label={assistantTitle}
          className="fixed right-4 bottom-4 z-50 flex max-h-[72vh] w-[calc(100vw-2rem)] max-w-md flex-col overflow-hidden rounded-2xl border border-line bg-white shadow-2xl sm:right-6 sm:bottom-6"
        >
          <header className="flex items-center gap-3 border-b border-line bg-slate-50/80 px-4 py-3.5">
            <span className="grid size-9 place-items-center rounded-xl bg-brand-600 text-white">
              <Sparkles className="size-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-sm font-semibold text-ink">{assistantTitle}</h2>
              <p className="truncate text-xs text-ink-muted">Read-only · {access.provider_label}</p>
            </div>
            <button type="button" className="btn-ghost text-xs" disabled={busy} onClick={() => {
              setMessages([])
              setInput('')
              setError('')
              setQueryStatus('')
              setQueryPeriod('this month')
              setGuidanceOpen(true)
            }}>New chat</button>
            <button
              type="button"
              className="btn-ghost px-2"
              aria-label={`Close ${assistantTitle}`}
              onClick={() => setOpen(false)}
            >
              <Cross className="size-4" />
            </button>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {builtIn && access.chat_configured ? (
              <div className="mb-4 rounded-xl border border-line bg-slate-50 p-3">
                <button type="button" aria-expanded={guidanceOpen} className="w-full text-left text-xs font-semibold text-brand-700" onClick={() => setGuidanceOpen(!guidanceOpen)}>
                  {guidanceOpen ? 'Hide guided questions' : 'Build a question · filters & shortcuts'}
                </button>
                {guidanceOpen ? <div className="mt-3 space-y-3">
                  <p className="text-xs text-ink-muted">Choose filters, then ask for a count or matching schedules.</p>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="text-xs text-ink-muted">Status
                      <select aria-label="Schedule status" value={queryStatus} disabled={busy} onChange={(event) => setQueryStatus(event.target.value)} className="mt-1 w-full rounded-lg border border-line bg-white p-2 text-ink">
                        <option value="">All statuses</option>
                        {['Booked', 'Locked', 'In progress', 'Validation pending', 'Successful', 'Completed', 'Failed', 'Rolled back', 'Cancelled'].map((value) => <option key={value} value={value.toLowerCase()}>{value}</option>)}
                      </select>
                    </label>
                    <label className="text-xs text-ink-muted">Period
                      <select aria-label="Schedule period" value={queryPeriod} disabled={busy} onChange={(event) => setQueryPeriod(event.target.value)} className="mt-1 w-full rounded-lg border border-line bg-white p-2 text-ink">
                        {['Today', 'This week', 'Next week', 'This month', 'Last month', 'Upcoming', 'This year'].map((value) => <option key={value} value={value.toLowerCase()}>{value}</option>)}
                        <option value="">All dates</option>
                      </select>
                    </label>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {['Count', 'Show', 'Summary'].map((action) => <button key={action} type="button" disabled={busy || (action === 'Summary' && !!queryStatus)} title={action === 'Summary' && queryStatus ? 'Choose All statuses for a summary across statuses' : undefined} className="rounded-lg border border-line bg-white px-3 py-2 text-xs text-brand-700 disabled:opacity-40" onClick={() => void send(`${action === 'Summary' ? 'Deployment summary' : `${action} ${queryStatus} schedules`} ${queryPeriod}`)}>{action}</button>)}
                  </div>
                  {queryStatus ? <p className="text-xs text-ink-muted">Count and Show use the selected status. Summary requires All statuses.</p> : null}
                </div> : null}
              </div>
            ) : null}
            {!access.chat_configured ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
                <p className="font-semibold">PDS Assistant is not configured.</p>
                <p className="mt-1 text-xs">
                  Check the backend AI provider settings and restart the application.
                </p>
              </div>
            ) : messages.length === 0 ? (
              <div>
                <p className="text-sm font-medium text-ink">Ask me about PDS schedules, releases and deployments.</p>
                <p className="mt-1 text-xs leading-5 text-ink-muted">I can read PDS data, but I cannot cancel, reschedule, assign or modify records.</p>
                <div className="mt-4 grid gap-2">
                  {EXAMPLES.map((example) => (
                    <button
                      key={example}
                      type="button"
                      disabled={busy}
                      className="rounded-xl border border-line bg-white px-3 py-2.5 text-left text-xs leading-5 text-ink-muted transition hover:border-brand-500/40 hover:bg-brand-50 hover:text-brand-700"
                      onClick={() => void send(example)}
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {messages.map((message, index) => (
                  <div
                    key={`${message.role}-${index}`}
                    className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[88%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm leading-6 ${
                        message.role === 'user'
                          ? 'rounded-br-md bg-brand-600 text-white'
                          : 'rounded-bl-md bg-slate-100 text-ink'
                      }`}
                    >
                      {message.content}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {busy ? (
              <div className="mt-3 flex items-center gap-2 text-xs text-ink-muted">
                <Spinner className="size-4" />
                Checking PDS…
              </div>
            ) : null}
            {error ? (
              <div role="alert" className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-700">
                {error}
              </div>
            ) : null}
            {messages.length > 0 && !busy && access.chat_configured ? (
              <div className="mt-4 flex flex-wrap gap-2" aria-label="Quick questions">
                {['Show schedules today', 'Deployment summary this month', 'How many tenants are configured?'].map((question) => <button key={question} type="button" className="rounded-full border border-line px-3 py-1.5 text-xs text-brand-700 hover:bg-brand-50" onClick={() => void send(question)}>{question}</button>)}
              </div>
            ) : null}
            <div ref={endRef} />
          </div>

          <form
            className="border-t border-line bg-white p-3"
            onSubmit={(event) => {
              event.preventDefault()
              void send()
            }}
          >
            <div className="flex items-end gap-2 rounded-xl border border-line bg-slate-50 p-2 focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100">
              <textarea
                aria-label={askLabel}
                rows={1}
                className="max-h-28 min-h-9 flex-1 resize-none bg-transparent px-1 py-2 text-sm outline-none placeholder:text-slate-400"
                placeholder={access.chat_configured ? `${askLabel}…` : 'Configure PDS Assistant to start chatting'}
                value={input}
                disabled={!access.chat_configured || busy}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    void send()
                  }
                }}
              />
              <button
                type="submit"
                className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-600 text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-40"
                aria-label={`Send to ${assistantTitle}`}
                disabled={!access.chat_configured || busy || !input.trim()}
              >
                {busy ? <Spinner className="size-4" /> : <Send className="size-4" />}
              </button>
            </div>
          </form>
        </section>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="fixed right-4 bottom-4 z-40 inline-flex items-center gap-2 rounded-full bg-brand-600 px-4 py-3 text-sm font-semibold text-white shadow-xl transition hover:-translate-y-0.5 hover:bg-brand-700 sm:right-6 sm:bottom-6"
          aria-label={askLabel}
        >
          <Sparkles className="size-5" />
          {askLabel}
          {!access.chat_configured ? <span className="size-2 rounded-full bg-amber-300" title="PDS Assistant is not configured" /> : null}
        </button>
      )}
    </>
  )
}
