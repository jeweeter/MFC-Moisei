import { useEffect, useMemo, useState } from 'react'
import {
  api, type Scenario, type ScenarioBrief, type WizardPackage,
} from '../api'
import Markdown from './Markdown'
import {
  IconBack, IconCheck, IconClock, IconCopy, IconPayment, IconSpark,
} from './Icons'

type Props = { scenarioId?: string; onAsk: (q?: string, serviceId?: string | null) => void }

export default function WizardPage({ scenarioId, onAsk }: Props) {
  const [list, setList] = useState<ScenarioBrief[]>([])
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [answers, setAnswers] = useState<Record<string, string[]>>({})
  const [step, setStep] = useState(0)
  const [pkg, setPkg] = useState<WizardPackage | null>(null)
  const [loading, setLoading] = useState(false)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    api.scenarios().then(setList).catch(() => setList([]))
  }, [])

  useEffect(() => {
    setPkg(null)
    setAnswers({})
    setStep(0)
    setChecked(new Set())
    if (!scenarioId) {
      setScenario(null)
      return
    }
    api.scenario(scenarioId).then(setScenario).catch(() => setScenario(null))
  }, [scenarioId])

  const current = scenario?.steps[step]
  const isLast = scenario ? step === scenario.steps.length - 1 : false

  const toggle = (stepId: string, optId: string, multi: boolean) => {
    setAnswers((a) => {
      const cur = a[stepId] || []
      if (!multi) return { ...a, [stepId]: cur.includes(optId) ? [] : [optId] }
      return {
        ...a,
        [stepId]: cur.includes(optId) ? cur.filter((x) => x !== optId) : [...cur, optId],
      }
    })
  }

  const build = async () => {
    if (!scenario) return
    setLoading(true)
    try {
      setPkg(await api.wizardPackage(scenario.id, answers))
    } finally {
      setLoading(false)
    }
  }

  const copyPackage = () => {
    if (!pkg) return
    const docs = pkg.checklist.common.map((c) => `— ${c.text}`).join('\n')
    const svcs = pkg.services.map((s, i) => `${i + 1}. ${s.shortTitle}${s.department ? ` (${s.department})` : ''}`).join('\n')
    navigator.clipboard?.writeText(
      `Пакет услуг: ${pkg.title}\n\nУслуги:\n${svcs}\n\nДокументы на весь пакет:\n${docs}`,
    )
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  const stages = useMemo(() => {
    if (!pkg) return []
    const map = new Map<number, typeof pkg.services>()
    pkg.services.forEach((s) => {
      map.set(s.stage, [...(map.get(s.stage) || []), s])
    })
    return [...map.entries()].sort((a, b) => a[0] - b[0])
  }, [pkg])

  // ----------------------------------------------------------- выбор сценария
  if (!scenarioId || !scenario) {
    return (
      <div className="wizard">
        <div className="page-head">
          <h1>Мастер по жизненной ситуации</h1>
          <p className="sub">
            Заявитель редко знает название услуги — он описывает ситуацию. Пройдите
            короткий опрос и получите сразу пакет связанных услуг: порядок обращения,
            общий список документов на один визит и сводку по срокам.
          </p>
        </div>
        <div className="scenarios">
          {list.map((s) => (
            <a key={s.id} href={`#/wizard/${s.id}`} className="scenario-card">
              <span className="scenario-emoji">{s.emoji}</span>
              <div className="scenario-body">
                <h3>{s.title}</h3>
                <p>{s.subtitle}</p>
                <div className="scenario-meta">
                  <span className="mono">{s.steps} {plural(s.steps, 'шаг', 'шага', 'шагов')}</span>
                  {s.lifeSituations.slice(0, 2).map((l) => (
                    <span key={l} className="chip">{l}</span>
                  ))}
                </div>
              </div>
            </a>
          ))}
          {list.length === 0 && [0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="skeleton" style={{ height: 132 }} />
          ))}
        </div>
      </div>
    )
  }

  // -------------------------------------------------------------- результат
  if (pkg) {
    return (
      <div className="wizard">
        <a className="btn ghost sm back" href="#/wizard"><IconBack size={15} /> Все ситуации</a>

        <header className="pkg-head card">
          <div>
            <div className="mono">пакет услуг подобран</div>
            <h1><span className="pkg-emoji">{pkg.emoji}</span> {pkg.title}</h1>
            <div className="pkg-answers">
              {pkg.answers.map((a, i) => (
                <span key={i} className="chip accent">{a.answer}</span>
              ))}
            </div>
          </div>
          <div className="pkg-stats">
            <Stat value={pkg.summary.servicesCount} label="услуг в пакете" />
            <Stat value={pkg.summary.departmentsCount} label="ведомств" />
            <Stat value={pkg.checklist.common.length} label="типов документов" />
          </div>
        </header>

        <div className="pkg-hint banner info">{pkg.summary.visitsHint}</div>

        {pkg.memo && (
          <div className="pkg-memo card">
            <div className="pkg-memo-head">
              <span className="chat-avatar sm">М</span>
              <div>
                <strong>Памятка от Моисея</strong>
                {pkg.memoCached && <span className="chip ok">из кэша</span>}
              </div>
            </div>
            <Markdown text={pkg.memo} />
          </div>
        )}

        <div className="pkg-grid">
          <section>
            <div className="section-title">
              <h2>Порядок обращения</h2>
              <button className="btn ghost sm" onClick={copyPackage}>
                <IconCopy size={14} /> {copied ? 'Скопировано' : 'Копировать пакет'}
              </button>
            </div>
            <div className="stages">
              {stages.map(([stage, items]) => (
                <div key={stage} className="stage">
                  <div className="stage-mark">
                    <span className="stage-n">{stage === 0 ? '★' : stage}</span>
                    <span className="stage-line" />
                  </div>
                  <div className="stage-items">
                    {items.map((s) => (
                      <article key={s.id} className="pkg-svc card">
                        <a href={`#/s/${encodeURIComponent(s.id)}`}>
                          <h3>{s.shortTitle}</h3>
                        </a>
                        <div className="pkg-svc-meta">
                          {s.department && <span className="chip">{s.department}</span>}
                          {s.variantCount > 1 && (
                            <span className="chip accent">{s.variantCount} муниципалитетов</span>
                          )}
                          {s.isFree && <span className="chip ok">бесплатно</span>}
                        </div>
                        <div className="pkg-svc-facts">
                          {s.term && (
                            <span title={s.term}><IconClock size={12} /> {trim(s.term, 62)}</span>
                          )}
                          {s.payment && !s.isFree && (
                            <span title={s.payment}><IconPayment size={12} /> {trim(s.payment, 62)}</span>
                          )}
                        </div>
                        <div className="pkg-svc-why">
                          {s.reasons.map((r) => <span key={r} className="chip">{r}</span>)}
                        </div>
                        <button className="btn ghost sm" onClick={() => onAsk(undefined, s.id)}>
                          <IconSpark size={13} /> Спросить об услуге
                        </button>
                      </article>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <aside className="pkg-check">
            <div className="section-title"><h2>Документы на весь пакет</h2></div>
            <p className="pkg-check-sub">
              Сведено по всем услугам пакета: попросите у заявителя один раз.
              Цифра — в скольких услугах документ требуется.
            </p>
            <div className="card pkg-check-card">
              {pkg.checklist.common.map((c) => {
                const on = checked.has(c.text)
                return (
                  <label key={c.text} className={`check-item ${on ? 'on' : ''}`}>
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() =>
                        setChecked((p) => {
                          const n = new Set(p)
                          n.has(c.text) ? n.delete(c.text) : n.add(c.text)
                          return n
                        })
                      }
                    />
                    <span className="check-box"><IconCheck size={12} /></span>
                    <span className="check-text">
                      {c.text}
                      {c.critical && <span className="chip accent tiny">обязательно</span>}
                    </span>
                    <span className="check-count">{c.count}</span>
                  </label>
                )
              })}
              {pkg.checklist.common.length === 0 && (
                <p className="mono">типовых документов не найдено</p>
              )}
            </div>

            {pkg.checklist.specific.length > 0 && (
              <details className="pkg-specific">
                <summary>Специфичные документы отдельных услуг ({pkg.checklist.specific.length})</summary>
                <ul>
                  {pkg.checklist.specific.map((c) => (
                    <li key={c.text}>{c.text}</li>
                  ))}
                </ul>
              </details>
            )}
          </aside>
        </div>

        <div className="pkg-actions">
          <button className="btn" onClick={() => { setPkg(null); setStep(0) }}>Изменить ответы</button>
          <a className="btn ghost" href="#/wizard">Другая ситуация</a>
        </div>
      </div>
    )
  }

  // ------------------------------------------------------------------ опрос
  return (
    <div className="wizard">
      <a className="btn ghost sm back" href="#/wizard"><IconBack size={15} /> Все ситуации</a>

      <div className="quiz card">
        <div className="quiz-progress">
          {scenario.steps.map((s, i) => (
            <span key={s.id} className={`quiz-dot ${i <= step ? 'on' : ''}`} />
          ))}
          <span className="mono">шаг {step + 1} из {scenario.steps.length}</span>
        </div>

        <div className="quiz-title">
          <span className="pkg-emoji">{scenario.emoji}</span>
          <div>
            <div className="mono">{scenario.title}</div>
            <h1>{current?.question}</h1>
            {current?.hint && <p className="sub">{current.hint}</p>}
          </div>
        </div>

        <div className="quiz-options">
          {current?.options.map((o) => {
            const on = (answers[current.id] || []).includes(o.id)
            return (
              <button
                key={o.id}
                className={`quiz-option ${on ? 'on' : ''}`}
                onClick={() => toggle(current.id, o.id, current.multi)}
              >
                <span className={`quiz-check ${current.multi ? 'square' : 'round'}`}>
                  {on && <IconCheck size={12} />}
                </span>
                {o.label}
              </button>
            )
          })}
        </div>

        <div className="quiz-actions">
          <button className="btn" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
            Назад
          </button>
          {isLast ? (
            <button className="btn primary" onClick={build} disabled={loading}>
              {loading ? 'Подбираем услуги…' : 'Собрать пакет услуг'}
            </button>
          ) : (
            <button className="btn primary" onClick={() => setStep((s) => s + 1)}>
              Далее
            </button>
          )}
          {!isLast && (
            <button className="btn ghost" onClick={build} disabled={loading}>
              Пропустить и собрать
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="pkg-stat">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  )
}

function trim(s: string, n: number) {
  return s.length > n ? s.slice(0, n).replace(/\s\S*$/, '') + '…' : s
}

function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few
  return many
}
