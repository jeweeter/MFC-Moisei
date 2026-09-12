import { useEffect, useMemo, useState } from 'react'
import { api, type Branch } from '../api'
import { IconPin, IconSearch } from './Icons'

export default function BranchesPage() {
  const [all, setAll] = useState<(Branch & { count: number })[]>([])
  const [q, setQ] = useState('')

  useEffect(() => {
    api.branches().then(setAll).catch(() => setAll([]))
  }, [])

  const items = useMemo(() => {
    const low = q.trim().toLowerCase()
    if (!low) return all
    return all.filter(
      (b) =>
        (b.name || '').toLowerCase().includes(low) ||
        (b.address || '').toLowerCase().includes(low),
    )
  }, [all, q])

  return (
    <div className="branches-page">
      <div className="page-head">
        <h1>Отделения МФЦ</h1>
        <p className="sub">
          {all.length} отделений из справочника <code>by_branch</code>. Показаны график
          работы, адрес и число услуг, которые отделение оказывает.
        </p>
      </div>

      <div className="search-box compact">
        <IconSearch size={17} className="search-icon" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Город, район, адрес или номер отделения"
        />
      </div>

      <div className="branch-grid">
        {items.map((b) => (
          <div key={b.id} className="card branch-card">
            <div className="branch-card-head">
              <IconPin size={15} />
              <h3>{b.name}</h3>
            </div>
            {b.address && <div className="branch-addr">{b.address}</div>}
            {b.schedule?.length > 0 && (
              <div className="branch-schedule">
                {b.schedule.map((s, i) => <div key={i}>{s}</div>)}
              </div>
            )}
            <div className="branch-card-meta">
              <span className="chip">{b.count} услуг</span>
              {b.windowCount && <span className="chip">{b.windowCount} окон</span>}
              {b.code && <span className="chip mono-chip">{b.code}</span>}
            </div>
          </div>
        ))}
        {items.length === 0 && all.length > 0 && (
          <div className="empty card"><h3>Ничего не найдено</h3></div>
        )}
        {all.length === 0 && [0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="skeleton" style={{ height: 150 }} />
        ))}
      </div>
    </div>
  )
}
