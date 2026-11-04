import type { CSSProperties, ElementType } from 'react'

// Text that rises in one character at a time. Words of Latin script stay together so they never break mid-word;
// every CJK character is its own unit, so lines still wrap anywhere. Screen readers get the plain text.

const TOKEN = /[⺀-鿿豈-﫿＀-￯]|[^\s⺀-鿿豈-﫿＀-￯]+|\s+/g

export function Reveal({ text, as: Tag = 'span', className = '', delay = 0 }: {
  text: string
  as?: ElementType
  className?: string
  delay?: number         // ms before the first character
}) {
  let i = 0
  return (
    <Tag className={`reveal ${className}`} aria-label={text}>
      {(text.match(TOKEN) ?? []).map((token, k) => /^\s+$/.test(token) ? ' ' : (
        <span key={k} className="word" aria-hidden="true">
          {Array.from(token).map(ch => (
            <span key={i} className="ch" style={{ '--d': `${delay + Math.min(i++, 40) * 24}ms` } as CSSProperties}>{ch}</span>
          ))}
        </span>
      ))}
    </Tag>
  )
}
