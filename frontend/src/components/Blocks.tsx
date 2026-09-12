import type { Block } from '../api'

/** Рендер структурированного текста раздела: списки, заголовки, таблицы. */
export default function Blocks({ blocks, text }: { blocks: Block[]; text: string }) {
  if (!blocks?.length) return <p className="block-p">{text}</p>
  return (
    <div className="blocks">
      {blocks.map((b, i) => {
        if (b.kind === 'rule') return <hr key={i} className="block-rule" />
        if (b.kind === 'heading') return <p key={i} className="block-h">{b.text}</p>
        if (b.kind === 'table_row') return <p key={i} className="block-tr">{b.text}</p>
        if (b.kind === 'list_item') {
          return (
            <div key={i} className="block-li">
              <span className="block-marker">{b.marker && /\d/.test(b.marker) ? b.marker : '•'}</span>
              <span>{b.text}</span>
            </div>
          )
        }
        return (
          <p key={i} className="block-p">
            {b.marker && <span className="block-marker inline">{b.marker}</span>}
            {b.text}
          </p>
        )
      })}
    </div>
  )
}
