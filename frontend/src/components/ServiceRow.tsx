import type { ServiceBrief } from '../api'
import { SECTION_ICONS, IconSpark } from './Icons'

const SECTION_LABEL: Record<string, string> = {
  title: 'название', documents: 'документы', payment: 'стоимость', term: 'срок',
  result: 'результат', reject: 'отказ', recipients: 'получатели', ordering: 'порядок',
}

export default function ServiceRow({
  item, index, onAsk,
}: {
  item: ServiceBrief
  index: number
  onAsk: (q?: string, serviceId?: string | null) => void
}) {
  const Icon = SECTION_ICONS[item.bestSection ?? 'documents'] ?? SECTION_ICONS.documents
  const total = item.variantTotal ?? 0

  return (
    <article
      className="srow fade-up"
      style={{ animationDelay: `${Math.min(index, 8) * 22}ms` }}
    >
      <a className="srow-main" href={`#/s/${encodeURIComponent(item.id)}`}>
        <div className="srow-top">
          <h3>{item.shortTitle}</h3>
          {item.completeness < 0.6 && (
            <span className="chip warn" title={`Заполнено ${Math.round(item.completeness * 100)}% разделов`}>
              неполные данные
            </span>
          )}
        </div>

        {item.snippet && (
          <p className="srow-snippet">
            <Icon size={13} className="srow-snippet-icon" />
            <span className="mono srow-section">
              {SECTION_LABEL[item.bestSection ?? ''] ?? 'фрагмент'}
            </span>
            {item.snippet}
          </p>
        )}

        <div className="srow-meta">
          {item.department && <span className="chip">{item.department}</span>}
          {total > 1 && (
            <span className="chip accent" title="Одна услуга, продублированная по муниципальным образованиям">
              {total} муниципалитетов
            </span>
          )}
          {item.lifeSituations.slice(0, 2).map((ls) => (
            <span key={ls} className="chip">{ls}</span>
          ))}
          {item.branchCount > 0 && (
            <span className="chip">{item.branchCount} отделений</span>
          )}
        </div>
      </a>

      <button
        className="srow-ask"
        onClick={() => onAsk(undefined, item.id)}
        title="Задать вопрос по этой услуге"
      >
        <IconSpark size={15} />
        <span>Спросить</span>
      </button>
    </article>
  )
}
