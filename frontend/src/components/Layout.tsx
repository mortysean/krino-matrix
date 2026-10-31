import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { t } from '../i18n'
import { IconChats, IconLogout, IconPlus, IconSettings, IconToday } from './icons'
import { Logo } from './Logo'

const NAV = [
  { to: '/', label: 'nav.today', icon: IconToday, end: true },
  { to: '/chats', label: 'nav.chats', icon: IconChats, end: false },
  { to: '/settings', label: 'nav.settings', icon: IconSettings, end: false },
] as const

export function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  return (
    <div className="shell">
      <aside className="side" aria-label="Navigation">
        <div className="brand"><Logo size={36} /></div>
        <button className="btn primary new-btn" onClick={() => navigate('/')}><IconPlus size={16} />{t('nav.new')}</button>
        {NAV.map((n, i) => (
          <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span className="nav-n">0{i + 1}</span><n.icon size={17} />{t(n.label)}
          </NavLink>
        ))}
        <div className="spacer" />
        <div className="who" title={user?.email}>{user?.email}</div>
        <button className="nav-item btn ghost" onClick={logout}><IconLogout size={17} />{t('nav.logout')}</button>
      </aside>
      <main className="main">
        <div className="mobile-top"><Logo size={26} /></div>
        {/* keyed by section so each page plays its entrance; /c/new → /c/<id> must not remount mid-turn */}
        <div key={pathname.split('/')[1]} className="route"><Outlet /></div>
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
