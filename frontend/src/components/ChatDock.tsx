import { useCallback, useEffect, useRef, useState } from 'react'
import { askStream, type Fragment, type Meta } from '../api'
import { IconClose, IconSend, IconSpark, SECTION_ICONS } from './Icons'
import Markdown from './Markdown'

type Msg = {
  id: string
  role: 'user' | 'assistant'
  text: string
  fragments?: Fragment[]
  cached?: boolean
  mode?: string
  latencyMs?: number
  streaming?: boolean
  error?: string
  serviceId?: string | null
}

const SUGGESTIONS = [
  'Какие документы нужны на загранпаспорт ребёнку?',
  'Сколько стоит выписка из ЕГРН?',
  'Как оформить маткапитал?',
  'Что нужно, если потерян паспорт?',
]

export default function ChatDock({
  open, onClose, seed, serviceContext, meta,
}: {
  open: boolean
  onClose: () => void
  seed: { question?: string; serviceId?: string | null; nonce: number }
  serviceContext: string | null
  meta: Meta | null
}) {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [scoped, setScoped] = useState(true)
  const [openFragments, setOpenFragments] = useState<string | null>(null)
  const [highlightCite, setHighlightCite] = useState<{ msg: string; n: number } | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const cancelRef = useRef<(() => void) | null>(null)
  const lastSeed = useRef(0)

  const scrollDown = useCallback(() => {
    requestAnimationFrame(() => {
      bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: 'smooth' })
    })
  }, [])

  const send = useCallback(
    (question: string, serviceId: string | null) => {
      const q = question.trim()
      if (!q || busy) return
      const userId = `u${Date.now()}`
      const botId = `a${Date.now()}`
      setMessages((m) => [
        ...m,
        { id: userId, role: 'user', text: q, serviceId },
        { id: botId, role: 'assistant', text: '', streaming: true, serviceId },
      ])
      setInput('')
      setBusy(true)
      scrollDown()

      cancelRef.current = askStream(q, serviceId, {
        onMeta: (m) =>
          setMessages((prev) =>
            prev.map((x) => (x.id === botId ? { ...x, fragments: m.fragments, mode: m.mode } : x)),
          ),
        onDelta: (t) => {
          setMessages((prev) =>
            prev.map((x) => (x.id === botId ? { ...x, text: x.text + t } : x)),
          )
          scrollDown()
        },
        onDone: (d) => {
          setMessages((prev) =>
            prev.map((x) =>
              x.id === botId
                ? {
                    ...x,
                    streaming: false,
                    cached: Boolean(d.cached),
                    mode: (d.mode as string) || x.mode,
                    latencyMs: d.latencyMs as number,
                  }
                : x,
            ),
          )
          setBusy(false)
          scrollDown()
        },
        onError: (e) => {
          setMessages((prev) =>
            prev.map((x) => (x.id === botId ? { ...x, streaming: false, error: e } : x)),
          )
          setBusy(false)
        },
      })
    },
    [busy, scrollDown],
  )

  useEffect(() => {
    if (!open || seed.nonce === lastSeed.current) return
    lastSeed.current = seed.nonce
    if (seed.question) send(seed.question, scoped ? (seed.serviceId ?? serviceContext) : null)
    else setTimeout(() => inputRef.current?.focus(), 320)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed.nonce, open])

  useEffect(() => () => cancelRef.current?.(), [])

  const activeService = scoped ? serviceContext : null

  return (
    <>
      <div className={`chat-scrim ${open ? 'on' : ''}`} onClick={onClose} />
      <aside className={`chat ${open ? 'open' : ''}`} aria-hidden={!open}>
        <header className="chat-head">
          <div className="chat-id">
            <span className="chat-avatar">М</span>
            <div>
              <strong>Моисей</strong>
              <span className={`chat-mode ${meta?.llm.enabled ? 'on' : ''}`}>
                {meta?.llm.enabled
                  ? `отвечает по базе знаний · ${meta.llm.model}`
                  : 'автономный режим — выдержки из базы'}
              </span>
            </div>
          </div>
          <button className="btn ghost sm" onClick={onClose} aria-label="Закрыть чат">
            <IconClose size={16} />
          </button>
        </header>

        {serviceContext && (
          <label className="chat-scope">
            <input type="checkbox" checked={scoped} onChange={(e) => setScoped(e.target.checked)} />
            <span className="switch-track"><span className="switch-thumb" /></span>
            Искать только в открытой услуге
          </label>
        )}

        <div className="chat-body" ref={bodyRef}>
          {messages.length === 0 && (
            <div className="chat-welcome">
              <div className="chat-welcome-mark"><IconSpark size={22} /></div>
              <h3>Спросите как коллегу</h3>
              <p>
                Я отвечаю только по базе знаний МФЦ и всегда показываю, из какого раздела
                какой услуги взят каждый факт. Если ответа в базе нет — так и скажу.
              </p>
              <div className="chat-suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chip clickable" onClick={() => send(s, activeService)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) =>
            m.role === 'user' ? (
              <div key={m.id} className="msg user">{m.text}</div>
            ) : (
              <div key={m.id} className="msg bot">
                {m.text ? (
                  <Markdown
                    text={m.text}
                    onCite={(n) => {
                      setOpenFragments(m.id)
                      setHighlightCite({ msg: m.id, n })
                      requestAnimationFrame(() => {
                        document
                          .getElementById(`frag-${m.id}-${n}`)
                          ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
                      })
                    }}
                  />
                ) : (
                  <div className="typing"><span /><span /><span /></div>
                )}

                {m.error && <div className="msg-error">{m.error}</div>}

                <div className="msg-meta">
                  {m.cached && <span className="chip ok" title="Ответ взят из кэша — без обращения к LLM">из кэша</span>}
                  {m.mode === 'extractive' && <span className="chip warn">автономный режим</span>}
                  {typeof m.latencyMs === 'number' && (
                    <span className="mono">{m.latencyMs} мс</span>
                  )}
                  {m.fragments && m.fragments.length > 0 && (
                    <button
                      className="btn ghost sm"
                      onClick={() => setOpenFragments(openFragments === m.id ? null : m.id)}
                    >
                      {openFragments === m.id ? 'Скрыть источники' : `Источники (${m.fragments.length})`}
                    </button>
                  )}
                </div>

                {openFragments === m.id && m.fragments && (
                  <div className="frags">
                    {m.fragments.map((f, i) => {
                      const Icon = SECTION_ICONS[f.section] ?? IconSpark
                      const n = i + 1
                      const hot = highlightCite?.msg === m.id && highlightCite.n === n
                      return (
                        <div
                          key={f.chunkId}
                          id={`frag-${m.id}-${n}`}
                          className={`frag ${hot ? 'hot' : ''}`}
                        >
                          <div className="frag-head">
                            <span className="frag-n">{n}</span>
                            <a href={`#/s/${encodeURIComponent(f.serviceId)}`} className="frag-title">
                              {f.serviceShort}
                            </a>
                          </div>
                          <div className="frag-sub">
                            <Icon size={12} /> {f.sectionLabel}
                            {f.department && <> · {f.department}</>}
                          </div>
                          <p className="frag-text">{f.text}</p>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            ),
          )}
        </div>

        <footer className="chat-foot">
          <div className="chat-input">
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              placeholder={
                activeService ? 'Вопрос по открытой услуге…' : 'Вопрос по любой услуге МФЦ…'
              }
              onChange={(e) => {
                setInput(e.target.value)
                e.target.style.height = 'auto'
                e.target.style.height = `${Math.min(e.target.scrollHeight, 132)}px`
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send(input, activeService)
                }
              }}
            />
            <button
              className="btn primary sm chat-send"
              disabled={!input.trim() || busy}
              onClick={() => send(input, activeService)}
              aria-label="Отправить"
            >
              <IconSend size={16} />
            </button>
          </div>
          <div className="chat-hint mono">
            enter — отправить · shift+enter — перенос · ctrl+j — открыть/закрыть
          </div>
        </footer>
      </aside>
    </>
  )
}
