// The KRINO mark keeps the triangle of the A: an outer triangle, and a filled inner one where the A's
// counter would be. The wordmark draws the A of MATRIX the same way.

export function Mark({ size = 26, spinning = false }: { size?: number; spinning?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="var(--fg)" />
      <path d="M16 6.5 26 25H6Z" fill="none" stroke="var(--bg)" strokeWidth="2.2" strokeLinejoin="round" />
      <path d="M16 14.5 20.2 22h-8.4Z" fill="var(--accent)" className={spinning ? 'mark-spin' : undefined} />
    </svg>
  )
}

function TriA() {
  return (
    <svg className="tri-a" viewBox="0 0 20 19" aria-hidden="true">
      <path d="M10 1.5 18.5 17.5h-17Z" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinejoin="round" />
    </svg>
  )
}

export function Logo({ size = 26 }: { size?: number }) {
  return (
    <span className="logo" aria-label="KRINO MATRIX">
      <Mark size={size} />
      <span className="word" aria-hidden="true">
        <span>KRINO</span>
        <span>M<TriA />TRIX</span>
      </span>
    </span>
  )
}
