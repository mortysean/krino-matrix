import type { SVGProps } from 'react'

type P = SVGProps<SVGSVGElement> & { size?: number }

function Icon({ size = 18, children, ...rest }: P) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...rest}>
      {children}
    </svg>
  )
}

export const IconToday = (p: P) => <Icon {...p}><path d="M12 3.5 21 19.5H3Z" /><path d="M12 11v4" /></Icon>
export const IconChats = (p: P) => <Icon {...p}><path d="M4 5h16v10H9l-5 4Z" /></Icon>
export const IconSettings = (p: P) => (
  <Icon {...p}><circle cx="12" cy="12" r="3" /><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" /></Icon>
)
export const IconAgents = (p: P) => <Icon {...p}><rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" /><rect x="4" y="13" width="7" height="7" rx="1.5" /><rect x="13" y="13" width="7" height="7" rx="1.5" /></Icon>
export const IconPlus = (p: P) => <Icon {...p}><path d="M12 5v14M5 12h14" /></Icon>
export const IconArrow = (p: P) => <Icon {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Icon>
export const IconChevron = (p: P) => <Icon {...p}><path d="m9 6 6 6-6 6" /></Icon>
export const IconPause = (p: P) => <Icon {...p}><path d="M9 5v14M15 5v14" /></Icon>
export const IconPlay = (p: P) => <Icon {...p}><path d="M7 5v14l12-7Z" /></Icon>
export const IconReplay = (p: P) => <Icon {...p}><path d="M4 12a8 8 0 1 0 2.3-5.7" /><path d="M4 4v4h4" /></Icon>
export const IconAlert = (p: P) => <Icon {...p}><path d="M12 4 21 20H3Z" /><path d="M12 10v4M12 17h.01" /></Icon>
export const IconInfo = (p: P) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></Icon>
export const IconCheck = (p: P) => <Icon {...p}><path d="m5 12 5 5 9-10" /></Icon>
export const IconTrash = (p: P) => <Icon {...p}><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" /></Icon>
export const IconSearch = (p: P) => <Icon {...p}><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></Icon>
export const IconLogout = (p: P) => <Icon {...p}><path d="M14 4h5v16h-5M10 8l-4 4 4 4M6 12h10" /></Icon>
