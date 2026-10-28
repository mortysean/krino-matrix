import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { t } from '../i18n'
import { IconAgents, IconChats, IconLogout, IconPlus, IconSettings, IconToday } from './icons'
import { Logo } from './Logo'

const NAV = [
  { to: '/', label: 'nav.today', icon: IconToday, end: true },
  { to: '/chats', label: 'nav.chats', icon: IconChats, end: false },
  { to: '/settings', label: 'nav.settings', icon: IconSettings, end: false },
] as const

export function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  return (
    <div className="shell">
      <aside className="side" aria-label="Navigation">
        <div className="brand"><Logo /></div>
        <button className="btn new-btn" onClick={() => navigate('/')}><IconPlus size={16} />{t('nav.new')}</button>
        {NAV.map(n => (
          <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <n.icon />{t(n.label)}
          </NavLink>
        ))}
        {/* Reserved for P2: no market or install actions until they work */}
        <span className="nav-item disabled" aria-disabled="true"><IconAgents />{t('nav.agents')}<span className="soon">{t('nav.soon')}</span></span>
        <div className="spacer" />
        <div className="who" title={user?.email}>{user?.email}</div>
        <button className="nav-item btn ghost" style={{ justifyContent: 'flex-start' }} onClick={logout}><IconLogout />{t('nav.logout')}</button>
      </aside>
      <main className="main">
        <div className="mobile-top"><Logo size={24} /></div>
        <Outlet />
      </main>
      <nav className="tabs" aria-label="Navigation">
        {NAV.map(n => (
          <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? 'active' : '')}>
            <n.icon size={20} />{t(n.label)}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
