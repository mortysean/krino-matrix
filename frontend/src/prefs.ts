import { useSyncExternalStore } from 'react'

// Per-viewer display preferences. Stored in the browser only; everything works without them.

export type Theme = 'light' | 'dark' | 'system'
export type Motion = 'auto' | 'reduced' | 'full'

interface Prefs { theme: Theme; motion: Motion }

function read(): Prefs {
  try {
    const raw = JSON.parse(localStorage.getItem('krino.prefs') ?? '{}')
    return { theme: raw.theme ?? 'light', motion: raw.motion ?? 'auto' }
  } catch {
    return { theme: 'light', motion: 'auto' }
  }
}

let prefs = read()
const listeners = new Set<() => void>()

const systemReduced = window.matchMedia('(prefers-reduced-motion: reduce)')
// Low-end devices get the reduced set by default: fewer cores or little memory
const lowEnd = (navigator.hardwareConcurrency ?? 8) <= 2 ||
  ((navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 8) <= 2

export function reducedMotion(): boolean {
  if (prefs.motion === 'reduced') return true
  if (prefs.motion === 'full') return false
  return systemReduced.matches || lowEnd
}

export function apply() {
  const root = document.documentElement
  root.dataset.theme = prefs.theme === 'system' ? 'system' : prefs.theme
  root.classList.toggle('reduce-motion', reducedMotion())
  root.classList.toggle('full-motion', prefs.motion === 'full')
}

export function setPrefs(next: Partial<Prefs>) {
  prefs = { ...prefs, ...next }
  try { localStorage.setItem('krino.prefs', JSON.stringify(prefs)) } catch { /* storage unavailable */ }
  apply()
  listeners.forEach(l => l())
}

systemReduced.addEventListener('change', () => { apply(); listeners.forEach(l => l()) })

function subscribe(l: () => void) {
  listeners.add(l)
  return () => { listeners.delete(l) }
}

export function usePrefs(): Prefs {
  return useSyncExternalStore(subscribe, () => prefs)
}

export function useReducedMotion(): boolean {
  usePrefs()
  return useSyncExternalStore(subscribe, reducedMotion)
}
