import { useEffect, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { Layout } from './components/Layout'
import { Mark } from './components/Logo'
import { apply } from './prefs'
import { AuthPage, ResetPage } from './pages/Auth'
import { ChatsPage } from './pages/Chats'
import { ConversationPage } from './pages/Conversation'
import { DecisionPage } from './pages/Decision'
import { SettingsPage } from './pages/Settings'
import { TodayPage } from './pages/Today'

function Background() {
  return <div className="bg" aria-hidden="true"><div className="glow" /></div>
}

function RequireUser({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const location = useLocation()
  if (user === undefined) return <div className="auth"><Mark size={30} spinning /></div>
  if (user === null) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

function GuestOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  if (user === undefined) return <div className="auth"><Mark size={30} spinning /></div>
  return user ? <Navigate to="/" replace /> : children
}

export default function App() {
  useEffect(apply, [])
  return (
    <AuthProvider>
      <BrowserRouter>
        <Background />
        <Routes>
          <Route path="/login" element={<GuestOnly><AuthPage mode="login" /></GuestOnly>} />
          <Route path="/register" element={<GuestOnly><AuthPage mode="register" /></GuestOnly>} />
          <Route path="/reset" element={<ResetPage />} />
          <Route element={<RequireUser><Layout /></RequireUser>}>
            <Route path="/" element={<TodayPage />} />
            <Route path="/chats" element={<ChatsPage />} />
            <Route path="/c/:id" element={<ConversationPage />} />
            <Route path="/d/:id" element={<DecisionPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
