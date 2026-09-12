import { useEffect, useState } from 'react'
import { api, type CacheStats, type Meta, type QualityReport } from '../api'
import { IconDatabase, IconLayers, IconSpark, IconWarning } from './Icons'

export default function InsightsPage({ meta }: { meta: Meta | null }) {
  const [quality, setQuality] = useState<QualityReport | null>(null)
  const [cache, setCache] = useState<CacheStats | null>(null)
  const [tab, setTab] = useState<'quality' | 'cache'>('quality')

  const reload = () => {
    api.quality().then(setQuality).catch(() => setQuality(null))
    api.cacheStats().then(setCache).catch(() => setCache(null))
  }
  useEffect(reload, [])

  return (
    <div className="insights">
      <div className="page-head">
        <h1>Данные и кэш</h1>
        <p className="sub">
          Что система знает о качестве исходной выгрузки и сколько экономит кэш ответов.
          Оба показателя — часть решения: оператор должен видеть, где база неполна,
          а руководитель — во что обходятся ответы.
        </p>
      </div>

      <div className="tabs">
        <button className={tab === 'quality' ? 'on' : ''} onClick={() => setTab('quality')}>
          <IconDatabase size={15} /> Качество базы знаний
        </button>
        <button className={tab === 'cache' ? 'on' : ''} onClick={() => setTab('cache')}>
          <IconSpark size={15} /> Кэш ответов LLM
        </button>
      </div>

      {tab === 'quality' && quality && (
        <>
          <div className="kpis">
            <Kpi value={quality.services} label="услуг в выгрузке" />
            <Kpi value={`${quality.noiseRemovedPct}%`} label="HTML-мусора удалено" accent />
            <Kpi value={quality.completeness.poor} label="услуг с неполной карточкой" warn={quality.completeness.poor > 0} />
            <Kpi value={quality.noLifeSituation} label="без жизненной ситуации" warn={quality.noLifeSituation > 0} />
            <Kpi value={meta?.stats.chunks ?? 0} label="фрагментов для RAG" />
          </div>

          <section className="card panel">
            <h2>Заполненность разделов</h2>
            <p className="panel-sub">
              Доля услуг, у которых раздел не пуст после очистки HTML. Пустой раздел —
              это вопрос, на который оператор в окне не получит ответа.
            </p>
            <div className="bars">
              {quality.sections.map((s) => (
                <div key={s.code} className="bar-row">
                  <span className="bar-label">{s.label}</span>
                  <div className="bar-track">
                    <div
                      className={`bar-fill ${s.fillRate < 0.95 ? 'warn' : ''}`}
                      style={{ width: `${s.fillRate * 100}%` }}
                    />
                  </div>
                  <span className="bar-value">{(s.fillRate * 100).toFixed(1)}%</span>
                  <span className="bar-extra mono">{s.empty} пусто · {s.withHtml} с разметкой</span>
                </div>
              ))}
            </div>
          </section>

          <div className="two-col">
            <section className="card panel">
              <h2><IconWarning size={16} /> Услуги с наименее полными карточками</h2>
              <p className="panel-sub">
                По ним ассистент физически не может дать полный ответ — их нужно
                дозаполнить в первую очередь.
              </p>
              <div className="worst-list">
                {quality.worst.slice(0, 12).map((w) => (
                  <a key={w.id} href={`#/s/${encodeURIComponent(w.id)}`} className="worst-item">
                    <div className="worst-title">{w.title}</div>
                    <div className="worst-meta">
                      <span className="chip warn">{Math.round(w.completeness * 100)}%</span>
                      {w.missing.slice(0, 4).map((m) => (
                        <span key={m} className="chip">нет: {m}</span>
                      ))}
                    </div>
                  </a>
                ))}
              </div>
            </section>

            <section className="card panel">
              <h2><IconLayers size={16} /> Ссылочная целостность</h2>
              <div className="facts-list">
                <FactRow label="Услуг без ведомства" value={quality.missingDepartment} />
                <FactRow label="Неизвестных id ведомств" value={quality.unknownDepartmentIds.length} />
                <FactRow label="Неизвестных id отделений" value={quality.unknownBranchCount} />
                <FactRow label="Услуг без отделений приёма" value={quality.noBranches} />
                <FactRow label="Услуг без жизненной ситуации" value={quality.noLifeSituation} />
                <FactRow label="Base64-картинок вырезано из текста" value={quality.imagesDropped} />
                <FactRow
                  label="Объём текста"
                  value={`${(quality.rawBytes / 1e6).toFixed(2)} → ${(quality.cleanBytes / 1e6).toFixed(2)} МБ`}
                />
              </div>
              <p className="panel-note">
                Идентификаторы услуг в <code>db_knowledge.id</code> и в
                <code> flat_classification.categories[].ids</code> принадлежат разным
                пространствам имён и не пересекаются: обратный индекс «ведомство → услуги»
                из справочника не применим. Связи восстановлены только по прямым полям услуги.
              </p>
            </section>
          </div>
        </>
      )}

      {tab === 'cache' && cache && (
        <>
          <div className="kpis">
            <Kpi value={cache.entries} label="записей в кэше" />
            <Kpi value={`${(cache.hitRate * 100).toFixed(0)}%`} label="попаданий" accent />
            <Kpi value={cache.hits} label="ответов из кэша" />
            <Kpi value={`$${cache.savedUsd.toFixed(3)}`} label="сэкономлено на API" accent />
            <Kpi value={`${cache.savedSeconds.toFixed(0)} с`} label="сэкономлено времени" />
          </div>

          <section className="card panel">
            <h2>Как работает кэш</h2>
            <p className="panel-sub">
              Ключ — пара «услуга + нормализованный вопрос». Вопрос сводится к набору
              лемм без служебных слов, поэтому «какие документы нужны на загранпаспорт»,
              «документы на загранпаспорт?» и «загранпаспорт какие документы» — одно
              попадание. Модель и версия промпта входят в ключ: после их смены кэш
              инвалидируется автоматически. Срок жизни записи — {cache.ttlDays} дней.
            </p>
            <div className="facts-list">
              <FactRow label="Режим" value={cache.mode === 'llm' ? `LLM (${cache.model})` : 'автономный'} />
              <FactRow label="Промахов" value={cache.misses} />
              <FactRow label="Сэкономлено входных токенов" value={cache.savedTokensIn.toLocaleString('ru')} />
              <FactRow label="Сэкономлено выходных токенов" value={cache.savedTokensOut.toLocaleString('ru')} />
            </div>
            <button
              className="btn sm"
              onClick={async () => { await api.cacheClear(); reload() }}
            >
              Очистить кэш
            </button>
          </section>

          <div className="two-col">
            <section className="card panel">
              <h2>Самые частые вопросы</h2>
              {cache.top.length === 0 && <p className="mono">кэш пуст — задайте пару вопросов Моисею</p>}
              <div className="qlist">
                {cache.top.map((q, i) => (
                  <div key={i} className="qitem">
                    <span className="qhits">{q.hits}</span>
                    <span className="qtext">{q.question}</span>
                  </div>
                ))}
              </div>
            </section>
            <section className="card panel">
              <h2>Последние обращения</h2>
              <div className="qlist">
                {cache.recent.map((q, i) => (
                  <div key={i} className="qitem">
                    <span className={`chip ${q.cached ? 'ok' : ''}`}>{q.cached ? 'кэш' : 'LLM'}</span>
                    <span className="qtext">{q.question}</span>
                  </div>
                ))}
                {cache.recent.length === 0 && <p className="mono">обращений ещё не было</p>}
              </div>
            </section>
          </div>
        </>
      )}

      {((tab === 'quality' && !quality) || (tab === 'cache' && !cache)) && (
        <div className="skeleton" style={{ height: 300 }} />
      )}
    </div>
  )
}

function Kpi({ value, label, accent, warn }: { value: number | string; label: string; accent?: boolean; warn?: boolean }) {
  return (
    <div className={`kpi ${accent ? 'accent' : ''} ${warn ? 'warn' : ''}`}>
      <b>{value}</b>
      <span>{label}</span>
    </div>
  )
}

function FactRow({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="fact-row">
      <span>{label}</span>
      <b>{value}</b>
    </div>
  )
}
