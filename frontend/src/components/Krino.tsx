import { useEffect, useRef } from 'react'
import { useReducedMotion } from '../prefs'

// Krino, the assistant: the line art of public/krino (made by tools/lineart.py) used as a mask, so the figure is
// drawn in the page's ink colour in either theme. It prints in from the top, floats, leans toward the pointer,
// and a light passes over the lines while she thinks.

type Mood = 'idle' | 'thinking'

export function KrinoFigure({ mood = 'idle', className = '' }: { mood?: Mood; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()

  useEffect(() => {
    const el = ref.current
    if (!el || reduced) return
    let frame = 0
    const move = (e: PointerEvent) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const r = el.getBoundingClientRect()
        const x = (e.clientX - (r.left + r.width / 2)) / window.innerWidth
        const y = (e.clientY - (r.top + r.height / 2)) / window.innerHeight
        el.style.setProperty('--px', x.toFixed(3))
        el.style.setProperty('--py', y.toFixed(3))
      })
    }
    window.addEventListener('pointermove', move, { passive: true })
    return () => { window.removeEventListener('pointermove', move); cancelAnimationFrame(frame) }
  }, [reduced])

  return (
    <div ref={ref} className={`krino ${mood} ${className}`} aria-hidden="true">
      <div className="krino-float"><div className="krino-ink" /></div>
      <div className="krino-scan" />
    </div>
  )
}

export function KrinoFace({ mood = 'idle', size = 32 }: { mood?: Mood; size?: number }) {
  return (
    <span className={`krino-face ${mood}`} style={{ width: size, height: size }} aria-hidden="true">
      <span className="krino-ink" />
    </span>
  )
}
