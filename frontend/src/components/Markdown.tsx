/** Мини-рендер Markdown, который реально встречается в ответах Моисея:
 *  **жирный**, _курсив_, списки, переносы и ссылки-цитаты вида [1]. */
import { Fragment } from 'react'

const INLINE = /(\*\*[^*]+\*\*|_[^_]+_|\[\d{1,2}\])/g

export default function Markdown({
  text, onCite,
}: {
  text: string
  onCite?: (n: number) => void
}) {
  const lines = text.split('\n')
  return (
    <div className="md">
      {lines.map((line, i) => {
        const trimmed = line.trim()
        if (!trimmed) return <div key={i} className="md-gap" />
        const bullet = /^[-•*]\s+/.test(trimmed)
        const numbered = /^\d{1,2}[.)]\s+/.exec(trimmed)
        const body = bullet ? trimmed.replace(/^[-•*]\s+/, '')
          : numbered ? trimmed.slice(numbered[0].length) : trimmed
        const content = <Inline text={body} onCite={onCite} />
        if (bullet || numbered) {
          return (
            <div key={i} className="md-li">
              <span className="md-marker">{numbered ? numbered[0].trim() : '•'}</span>
              <span>{content}</span>
            </div>
          )
        }
        if (trimmed.startsWith('⚠️')) {
          return <div key={i} className="md-warn">{content}</div>
        }
        return <p key={i} className="md-p">{content}</p>
      })}
    </div>
  )
}

function Inline({ text, onCite }: { text: string; onCite?: (n: number) => void }) {
  const parts = text.split(INLINE).filter((p) => p !== '')
  return (
    <>
      {parts.map((part, i) => {
        if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={i}>{part.slice(2, -2)}</strong>
        if (/^_[^_]+_$/.test(part)) return <em key={i}>{part.slice(1, -1)}</em>
        const cite = /^\[(\d{1,2})\]$/.exec(part)
        if (cite) {
          const n = Number(cite[1])
          return (
            <button key={i} className="cite" onClick={() => onCite?.(n)} title="Показать источник">
              {n}
            </button>
          )
        }
        return <Fragment key={i}>{part}</Fragment>
      })}
    </>
  )
}
