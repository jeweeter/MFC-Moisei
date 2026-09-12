import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type Meta, type SearchFilters, type SearchResponse } from '../api'
import { IconLayers, IconSearch, IconSpark } from './Icons'
import ServiceRow from './ServiceRow'

const EXAMPLES = [
  'какие документы на загранпаспорт ребёнку',
  'скок стоит выписка егрн',
  'маткапитал распорядиться',
  'сво выплаты семье погибшего',
  'ghjgbcrf',
  'банкротство физлица через мфц',
]

const RECENT_KEY = 'moisei.recent'

function loadRecent(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]').slice(0, 6)
  } catch {
    return []
  }
}

function pushRecent(q: string) {
  const list = [q, ...loadRecent().filter((x) => x !== q)].slice(0, 6)
  localStorage.setItem(RECENT_KEY, JSON.stringify(list))
}

type Props = { meta: Meta | null; onAsk: (q?: string, serviceId?: string | null) => void }

export default function SearchPage({ meta, onAsk }: Props) {
  const [query, setQuery] = useState(() => sessionStorage.getItem('moisei.q') || '')
  const [filters, setFilters] = useState<SearchFilters>({})
  const [data, setData] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [grouped, setGrouped] = useState(true)
  const [recent, setRecent] = useState<string[]>(loadRecent)
  const reqId = useRef(0)

  const hasFilters = useMemo(
    () => Object.values(filters).some((v) => v && v.length),
    [filters],
  )

  const run = useCallback(
    async (q: string, f: SearchFilters, group: boolean) => {
      if (!q.trim() && !Object.values(f).some((v) => v && v.length)) {
        setData(null)
        return
      }
      const id = ++reqId.current
      setLoading(true)
      try {
        const res = await api.search(q, f, 24, group)
        if (id === reqId.current) setData(res)
      } catch {
        if (id === reqId.current) setData(null)
      } finally {
        if (id === reqId.current) setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    sessionStorage.setItem('moisei.q', query)
    const t = setTimeout(() => run(query, filters, grouped), query ? 180 : 0)
    return () => clearTimeout(t)
  }, [query, filters, grouped, run])

  const toggle = (key: keyof SearchFilters, id: string) => {
    setFilters((f) => {
      const cur = f[key] || []
      const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]
      return { ...f, [key]: next }
    })
  }

  const submit = () => {
    if (query.trim()) {
      pushRecent(query.trim())
      setRecent(loadRecent())
    }
  }

  const analysis = data?.analysis

  return (
    <div className="search-page">
      <div className="hero">
        <div className="hero-inner">
          <div className="mono">единое окно знаний · {meta?.app.region ?? 'Тульская область'}</div>
          <h1>Найдите ответ по услуге за секунды</h1>
          <p className="hero-sub">
            Поиск понимает сокращения, просторечия и опечатки: «загран», «маткапитал»,
            «прописка», даже набранное в латинской раскладке. Всё берётся из выгрузки
            базы знаний mfc71.ru — с показом первоисточника.
          </p>

          <div className="search-box">
            <IconSearch size={19} className="search-icon" />
            <input
              id="main-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              placeholder="Например: какие документы нужны на загранпаспорт ребёнку"
              autoComplete="off"
              spellCheck={false}
            />
            {query && (
              <button className="btn ghost sm" onClick={() => setQuery('')}>Очистить</button>
            )}
            <button className="btn primary sm ask-btn" onClick={() => onAsk(query || undefined, null)}>
              <IconSpark size={14} /> Спросить Моисея
            </button>
          </div>

          {!query && (
            <div className="examples">
              <span className="mono">попробуйте</span>
              {(recent.length ? recent : EXAMPLES).map((ex) => (
                <button key={ex} className="chip clickable" onClick={() => setQuery(ex)}>
                  {ex}
                </button>
              ))}
              {recent.length > 0 && (
                <button
                  className="btn ghost sm"
                  onClick={() => {
                    localStorage.removeItem(RECENT_KEY)
                    setRecent([])
                  }}
                >
                  очистить историю
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {analysis && (analysis.hints.length > 0 || analysis.layoutFixed || analysis.corrections.length > 0) && (
        <div className="understanding fade-up">
          <span className="mono">как понят запрос</span>
          <div className="understanding-items">
            {analysis.layoutFixed && (
              <span className="chip accent">раскладка → «{analysis.normalized}»</span>
            )}
            {analysis.corrections.map((c) => (
              <span key={c.from} className="chip warn">
                опечатка: {c.from} → {c.to}
              </span>
            ))}
            {analysis.hints.map((h) => (
              <span key={h} className="chip">{h}</span>
            ))}
          </div>
        </div>
      )}

      <div className="content-grid">
        <aside className="filters">
          <FilterGroup
            title="Жизненная ситуация"
            items={meta?.lifeSituations ?? []}
            selected={filters.lifeSituation ?? []}
            onToggle={(id) => toggle('lifeSituation', id)}
            max={8}
          />
          <FilterGroup
            title="Ведомство"
            items={meta?.departments ?? []}
            selected={filters.department ?? []}
            onToggle={(id) => toggle('department', id)}
            max={7}
          />
          <FilterGroup
            title="Категория заявителя"
            items={meta?.recipients ?? []}
            selected={filters.recipient ?? []}
            onToggle={(id) => toggle('recipient', id)}
            max={3}
          />
          {hasFilters && (
            <button className="btn sm" onClick={() => setFilters({})}>
              Сбросить фильтры
            </button>
          )}
        </aside>

        <section className="results">
          <div className="results-head">
            <div>
              {loading ? (
                <span className="mono">поиск…</span>
              ) : data ? (
                <span className="mono">
                  найдено {data.results.length} · {data.took} мс
                </span>
              ) : (
                <span className="mono">введите запрос или выберите фильтр</span>
              )}
            </div>
            <label className="switch" title="Свести муниципальные дубли одной услуги в одну строку">
              <input type="checkbox" checked={grouped} onChange={(e) => setGrouped(e.target.checked)} />
              <span className="switch-track"><span className="switch-thumb" /></span>
              <IconLayers size={14} />
              Группировать дубли по МО
            </label>
          </div>

          {loading && !data && (
            <div className="stack">
              {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton row-skeleton" />)}
            </div>
          )}

          {data && data.results.length === 0 && (
            <div className="empty card">
              <h3>Ничего не найдено</h3>
              <p>
                В базе знаний нет услуги под такой запрос. Попробуйте переформулировать —
                или спросите Моисея: он покажет ближайшие по смыслу разделы и честно
                скажет, если ответа в базе нет.
              </p>
              <button className="btn primary" onClick={() => onAsk(query, null)}>
                <IconSpark size={15} /> Спросить Моисея
              </button>
            </div>
          )}

          <div className="stack">
            {data?.results.map((r, i) => (
              <ServiceRow key={r.id} item={r} index={i} onAsk={onAsk} />
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

function FilterGroup({
  title, items, selected, onToggle, max,
}: {
  title: string
  items: { id: string; name: string; shortName?: string; count: number }[]
  selected: string[]
  onToggle: (id: string) => void
  max: number
}) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? items : items.slice(0, max)
  return (
    <div className="filter-group">
      <div className="mono">{title}</div>
      <div className="filter-items">
        {shown.map((it) => (
          <button
            key={it.id}
            className={`filter-item ${selected.includes(it.id) ? 'on' : ''}`}
            onClick={() => onToggle(it.id)}
            title={it.name}
          >
            <span className="filter-name">{it.shortName || it.name}</span>
            <span className="filter-count">{it.count}</span>
          </button>
        ))}
      </div>
      {items.length > max && (
        <button className="btn ghost sm" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Свернуть' : `Ещё ${items.length - max}`}
        </button>
      )}
    </div>
  )
}
