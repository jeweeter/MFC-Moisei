import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type ServiceCard } from '../api'
import Blocks from './Blocks'
import {
  IconBack, IconCheck, IconCopy, IconDocs, IconPin, IconSpark, SECTION_ICONS,
} from './Icons'

type Props = { id: string; onAsk: (q?: string, serviceId?: string | null) => void }

const QUICK_QUESTIONS = [
  'Какие документы нужны?',
  'Сколько стоит?',
  'Какой срок оказания?',
  'Кто может обратиться?',
  'В каких случаях откажут?',
  'Что получит заявитель на руки?',
]

export default function ServicePage({ id, onAsk }: Props) {
  const [card, setCard] = useState<ServiceCard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState<string>('documents')
  const [rawOpen, setRawOpen] = useState<string | null>(null)
  const [raw, setRaw] = useState<string>('')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [copied, setCopied] = useState(false)
  const [branchQuery, setBranchQuery] = useState('')
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({})

  useEffect(() => {
    setCard(null)
    setError(null)
    setRawOpen(null)
    api.service(id).then(setCard).catch((e) => setError(String(e)))
    try {
      setChecked(new Set(JSON.parse(localStorage.getItem(`moisei.check.${id}`) || '[]')))
    } catch {
      setChecked(new Set())
    }
  }, [id])

  useEffect(() => {
    if (!card) return
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
        if (visible) setActive(visible.target.id.replace('sec-', ''))
      },
      { rootMargin: '-90px 0px -70% 0px', threshold: 0 },
    )
    Object.values(sectionRefs.current).forEach((el) => el && obs.observe(el))
    return () => obs.disconnect()
  }, [card])

  const docItems = useMemo(() => {
    const sec = card?.sections.find((s) => s.code === 'documents')
    if (!sec) return []
    return sec.blocks
      .filter((b) => b.kind !== 'rule' && b.text.length > 8)
      .map((b, i) => ({ key: `${i}`, text: b.text, heading: b.kind === 'heading', marker: b.marker }))
  }, [card])

  const toggleCheck = (key: string) => {
    setChecked((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      localStorage.setItem(`moisei.check.${id}`, JSON.stringify([...next]))
      return next
    })
  }

  const openRaw = async (section: string) => {
    if (rawOpen === section) {
      setRawOpen(null)
      return
    }
    setRawOpen(section)
    setRaw('')
    try {
      const r = await api.raw(id, section)
      setRaw(r.raw)
    } catch {
      setRaw('Не удалось получить исходный текст.')
    }
  }

  const copyChecklist = () => {
    const lines = docItems
      .filter((d) => !d.heading)
      .map((d, i) => `${i + 1}. ${d.text}`)
    navigator.clipboard?.writeText(
      `${card?.title}\n\nПеречень документов:\n${lines.join('\n')}`,
    )
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  if (error) return <div className="banner error">Не удалось загрузить услугу: {error}</div>
  if (!card) {
    return (
      <div className="stack">
        <div className="skeleton" style={{ height: 120 }} />
        <div className="skeleton" style={{ height: 320 }} />
      </div>
    )
  }

  const term = card.sections.find((s) => s.code === 'term')
  const payment = card.sections.find((s) => s.code === 'payment')
  const branches = card.branches.filter(
    (b) =>
      !branchQuery ||
      (b.name || '').toLowerCase().includes(branchQuery.toLowerCase()) ||
      (b.address || '').toLowerCase().includes(branchQuery.toLowerCase()),
  )

  return (
    <div className="service-page">
      <a className="btn ghost sm back" href="#/"><IconBack size={15} /> К поиску</a>

      <header className="svc-head card">
        <div className="svc-head-main">
          <div className="mono">{card.department ?? 'ведомство не указано'}</div>
          <h1>{card.shortTitle}</h1>
          {card.shortTitle !== card.title && (
            <details className="full-title">
              <summary>Полное наименование по регламенту</summary>
              <p>{card.title}</p>
            </details>
          )}
          <div className="svc-chips">
            {card.recipients.map((r) => <span key={r} className="chip">{r}</span>)}
            {card.lifeSituations.map((l) => <span key={l} className="chip accent">{l}</span>)}
            <span className="chip mono-chip">id {card.id}</span>
            {card.completeness < 1 && (
              <span className="chip warn">
                заполнено {Math.round(card.completeness * 100)}% разделов
              </span>
            )}
          </div>
          {card.variants.length > 1 && (
            <div className="variants">
              <span className="mono">та же услуга в других МО ({card.variants.length})</span>
              <div className="variants-list">
                {card.variants.map((v) => (
                  <a
                    key={v.id}
                    href={`#/s/${encodeURIComponent(v.id)}`}
                    className={`chip clickable ${v.current ? 'accent' : ''}`}
                  >
                    {v.label}
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="svc-facts">
          <Fact label="Срок" value={firstLine(term?.text)} icon="term" />
          <Fact label="Стоимость" value={firstLine(payment?.text)} icon="payment" />
          <Fact label="Отделений" value={`${card.branchCount}`} icon="ordering" />
          <button className="btn primary svc-ask" onClick={() => onAsk(undefined, card.id)}>
            <IconSpark size={15} /> Спросить Моисея об услуге
          </button>
        </div>
      </header>

      <div className="quick-q">
        <span className="mono">частые вопросы оператора</span>
        {QUICK_QUESTIONS.map((q) => (
          <button key={q} className="chip clickable" onClick={() => onAsk(q, card.id)}>{q}</button>
        ))}
      </div>

      <div className="svc-grid">
        <nav className="svc-nav">
          {card.sections.map((s) => {
            const Icon = SECTION_ICONS[s.code] ?? IconDocs
            return (
              <a
                key={s.code}
                href={`#sec-${s.code}`}
                className={`svc-nav-item ${active === s.code ? 'on' : ''}`}
                onClick={(e) => {
                  e.preventDefault()
                  sectionRefs.current[s.code]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                }}
              >
                <Icon size={15} /> {s.label}
              </a>
            )
          })}
          {card.missingSections.length > 0 && (
            <div className="svc-missing">
              <span className="mono">нет данных</span>
              {card.missingSections.map((m) => <span key={m} className="chip warn">{m}</span>)}
            </div>
          )}
        </nav>

        <div className="svc-body">
          {card.sections.map((s) => {
            const Icon = SECTION_ICONS[s.code] ?? IconDocs
            return (
              <section
                key={s.code}
                id={`sec-${s.code}`}
                ref={(el) => { sectionRefs.current[s.code] = el }}
                className="svc-section card"
              >
                <div className="svc-section-head">
                  <h2><Icon size={17} /> {s.label}</h2>
                  <div className="svc-section-actions">
                    {s.code === 'documents' && (
                      <button className="btn ghost sm" onClick={copyChecklist}>
                        <IconCopy size={14} /> {copied ? 'Скопировано' : 'Копировать список'}
                      </button>
                    )}
                    <button className="btn ghost sm" onClick={() => openRaw(s.code)}>
                      {rawOpen === s.code ? 'Скрыть оригинал' : 'Оригинал из базы'}
                    </button>
                  </div>
                </div>

                {s.code === 'documents' ? (
                  <div className="checklist">
                    <div className="checklist-head">
                      <span className="mono">чек-лист приёма</span>
                      <span className="checklist-progress">
                        {[...checked].length} / {docItems.filter((d) => !d.heading).length}
                      </span>
                    </div>
                    {docItems.map((d) =>
                      d.heading ? (
                        <p key={d.key} className="block-h">{d.text}</p>
                      ) : (
                        <label key={d.key} className={`check-item ${checked.has(d.key) ? 'on' : ''}`}>
                          <input
                            type="checkbox"
                            checked={checked.has(d.key)}
                            onChange={() => toggleCheck(d.key)}
                          />
                          <span className="check-box"><IconCheck size={12} /></span>
                          <span className="check-text">
                            {d.marker && <b className="block-marker inline">{d.marker}</b>}
                            {d.text}
                          </span>
                        </label>
                      ),
                    )}
                  </div>
                ) : (
                  <Blocks blocks={s.blocks} text={s.text} />
                )}

                {s.links.length > 0 && (
                  <div className="svc-links">
                    <span className="mono">ссылки из регламента</span>
                    {s.links.map((l) => (
                      <a key={l.href} href={l.href} target="_blank" rel="noreferrer" className="chip clickable">
                        {l.title.slice(0, 70)}
                      </a>
                    ))}
                  </div>
                )}

                {rawOpen === s.code && (
                  <div className="raw-view">
                    <div className="mono">исходный текст из db_knowledge.json (поле как есть)</div>
                    <pre>{raw || 'загрузка…'}</pre>
                  </div>
                )}
              </section>
            )
          })}

          <section className="svc-section card">
            <div className="svc-section-head">
              <h2><IconPin size={17} /> Где принимают ({card.branchCount})</h2>
              <input
                className="branch-search"
                placeholder="Поиск по адресу или названию"
                value={branchQuery}
                onChange={(e) => setBranchQuery(e.target.value)}
              />
            </div>
            <div className="branch-list">
              {branches.slice(0, 40).map((b) => (
                <div key={b.id} className="branch">
                  <div className="branch-name">{b.name}</div>
                  {b.address && <div className="branch-addr">{b.address}</div>}
                  {b.schedule?.length > 0 && (
                    <div className="branch-sched">{b.schedule.join(' · ')}</div>
                  )}
                </div>
              ))}
              {branches.length > 40 && (
                <div className="mono">…и ещё {branches.length - 40}. Уточните поиск.</div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

/** Первая содержательная строка раздела.
 *  Пропускает строки-заголовки вида «Срок предоставления:» — в плитке
 *  «Срок» оператору нужно значение, а не повтор названия поля. */
function firstLine(text?: string) {
  if (!text) return '—'
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)
  const meaningful =
    lines.find((l) => l.length > 24 && !l.endsWith(':') && /\d|бесплат|без взим|не взим/i.test(l)) ??
    lines.find((l) => l.length > 24 && !l.endsWith(':')) ??
    lines[0]
  if (!meaningful) return '—'
  return meaningful.length > 96
    ? meaningful.slice(0, 96).replace(/\s\S*$/, '') + '…'
    : meaningful
}

function Fact({ label, value, icon }: { label: string; value: string; icon: string }) {
  const Icon = SECTION_ICONS[icon] ?? IconDocs
  return (
    <div className="fact">
      <div className="fact-label"><Icon size={13} /> {label}</div>
      <div className="fact-value" title={value}>{value}</div>
    </div>
  )
}
