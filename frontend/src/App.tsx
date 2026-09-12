import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type Meta } from './api'
import ChatDock from './components/ChatDock'
import {
  IconChart, IconCompass, IconMoon, IconPin, IconSearch, IconSun,
} from './components/Icons'
import BranchesPage from './components/BranchesPage'
import InsightsPage from './components/InsightsPage'
import SearchPage from './components/SearchPage'
import ServicePage from './components/ServicePage'
import WizardPage from './components/WizardPage'

export type Route =
  | { name: 'search' }
  | { name: 'service'; id: string }
  | { name: 'wizard'; id?: string }
  | { name: 'insights' }
  | { name: 'branches' }

function parseHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, '')
  const [head, tail] = [h.split('/')[0], h.split('/').slice(1).join('/')]
  if (head === 's' && tail) return { name: 'service', id: decodeURIComponent(tail) }
  if (head === 'wizard') return { name: 'wizard', id: tail || undefined }
  if (head === 'insights') return { name: 'insights' }
  if (head === 'branches') return { name: 'branches' }
  return { name: 'search' }
}

export function navigate(to: string) {
  window.location.hash = to
}

const NAV = [
  { key: 'search', href: '#/', label: 'Поиск по услугам', hint: 'S', Icon: IconSearch },
  { key: 'wizard', href: '#/wizard', label: 'Жизненные ситуации', hint: 'Ж', Icon: IconCompass },
  { key: 'branches', href: '#/branches', label: 'Отделения МФЦ', hint: 'О', Icon: IconPin },
  { key: 'insights', href: '#/insights', label: 'Данные и кэш', hint: 'Д', Icon: IconChart },
] as const

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [theme, setTheme] = useState<'light' | 'dark'>(
    () => (localStorage.getItem('moisei.theme') as 'light' | 'dark') || 'light',
  )
  const [chatOpen, setChatOpen] = useState(false)
  const [chatSeed, setChatSeed] = useState<{ question?: string; serviceId?: string | null; nonce: number }>(
    { nonce: 0 },
  )

  useEffect(() => {
    const onHash = () => {
      setRoute(parseHash())
      window.scrollTo({ top: 0 })
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('moisei.theme', theme)
  }, [theme])

  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setError(String(e)))
  }, [])

  const openChat = useCallback((question?: string, serviceId?: string | null) => {
    setChatSeed((s) => ({ question, serviceId, nonce: s.nonce + 1 }))
    setChatOpen(true)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      const typing = tag === 'INPUT' || tag === 'TEXTAREA'
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'j') {
        e.preventDefault()
        setChatOpen((v) => !v)
      }
      if (e.key === '/' && !typing) {
        e.preventDefault()
        document.getElementById('main-search')?.focus()
      }
      if (e.key === 'Escape' && chatOpen) setChatOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [chatOpen])

  const serviceContext = route.name === 'service' ? route.id : null
  const activeKey = useMemo(() => {
    if (route.name === 'service') return 'search'
    return route.name
  }, [route])

  return (
    <div className={`shell ${chatOpen ? 'chat-open' : ''}`}>
      <aside className="rail">
        <a className="brand" href="#/">
          <span className="brand-mark" aria-hidden>
            <span className="brand-mark-glyph">М</span>
          </span>
          <span className="brand-text">
            <strong>Моисей</strong>
            <span>помощник оператора МФЦ</span>
          </span>
        </a>

        <nav className="nav">
          {NAV.map(({ key, href, label, Icon }) => (
            <a key={key} href={href} className={`nav-item ${activeKey === key ? 'active' : ''}`}>
              <Icon size={17} />
              <span>{label}</span>
            </a>
          ))}
        </nav>

        <div className="rail-foot">
          {meta && (
            <div className="rail-stats">
              <div className="rail-stat">
                <b>{meta.stats.services}</b>
                <span>услуг</span>
              </div>
              <div className="rail-stat">
                <b>{meta.stats.departments}</b>
                <span>ведомств</span>
              </div>
              <div className="rail-stat">
                <b>{meta.stats.branches}</b>
                <span>отделений</span>
              </div>
            </div>
          )}
          <div className={`mode-badge ${meta?.llm.enabled ? 'on' : 'off'}`}>
            <span className="dot" />
            {meta?.llm.enabled ? `LLM · ${meta.llm.model}` : 'Автономный режим'}
          </div>
          <button
            className="btn ghost sm theme-toggle"
            onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
            aria-label="Переключить тему"
          >
            {theme === 'light' ? <IconMoon size={15} /> : <IconSun size={15} />}
            {theme === 'light' ? 'Тёмная тема' : 'Светлая тема'}
          </button>
        </div>
      </aside>

      <main className="main">
        {error && (
          <div className="banner error">
            Не удалось связаться с сервером: {error}. Проверьте, что backend запущен на :8000.
          </div>
        )}
        {route.name === 'search' && <SearchPage meta={meta} onAsk={openChat} />}
        {route.name === 'service' && <ServicePage id={route.id} onAsk={openChat} />}
        {route.name === 'wizard' && <WizardPage scenarioId={route.id} onAsk={openChat} />}
        {route.name === 'insights' && <InsightsPage meta={meta} />}
        {route.name === 'branches' && <BranchesPage />}
      </main>

      <button
        className={`fab ${chatOpen ? 'hidden' : ''}`}
        onClick={() => openChat(undefined, serviceContext)}
        aria-label="Спросить Моисея (Ctrl+J)"
        title="Спросить Моисея — Ctrl+J"
      >
        <span className="fab-ring" aria-hidden />
        <span className="fab-glyph">М</span>
      </button>

      <ChatDock
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        seed={chatSeed}
        serviceContext={serviceContext}
        meta={meta}
      />
    </div>
  )
}
