import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type ConversationSummary } from '../api'
import { IconSearch, IconTrash } from '../components/icons'
import { Empty, Toast, useToast } from '../components/States'
import { getLocale, t } from '../i18n'

export function ChatsPage() {
  const [q, setQ] = useState('')
  const [items, setItems] = useState<ConversationSummary[] | null>(null)
  const [toast, showToast] = useToast()

  useEffect(() => {
    const id = window.setTimeout(() => api.conversations(q).then(setItems, () => setItems([])), q ? 250 : 0)
    return () => window.clearTimeout(id)
  }, [q])

  const remove = async (c: ConversationSummary) => {
    if (!window.confirm(t('chats.confirmDelete'))) return
    try {
      await api.deleteConversation(c.id)
      setItems(list => list?.filter(x => x.id !== c.id) ?? null)
    } catch {
      showToast(t('err.generic'))
    }
  }

  const date = (s: string) => new Date(s).toLocaleDateString(getLocale() === 'zh' ? 'zh-CN' : 'en', { month: 'short', day: 'numeric' })

  return (
    <div className="page narrow stack" style={{ gap: 20 }}>
      <h1 className="h2">{t('chats.title')}</h1>
      <div className="panel row" style={{ padding: '0 14px', gap: 8, flexWrap: 'nowrap' }}>
        <IconSearch size={17} className="muted" />
        <label htmlFor="search" className="sr-only">{t('chats.search')}</label>
        <input id="search" className="input" style={{ border: 0, boxShadow: 'none', padding: '12px 0', background: 'transparent' }}
          placeholder={t('chats.search')} value={q} onChange={e => setQ(e.target.value)} />
      </div>
      {items === null ? null : items.length === 0 ? <Empty>{q ? t('chats.noMatch') : t('chats.empty')}</Empty> : (
        <div className="list">
          {items.map(c => (
            <div key={c.id} className="list-item" style={{ padding: 0, gap: 0 }}>
              <Link to={`/c/${c.id}`} className="grow" style={{ padding: '14px 16px', minWidth: 0 }}>
                <div className="title">{c.title}</div>
                <div className="sub">{date(c.updated_at)} · {c.preview}</div>
              </Link>
              <button className="btn ghost sm" style={{ marginRight: 8 }} onClick={() => remove(c)} aria-label={`${t('chats.delete')} ${c.title}`}>
                <IconTrash size={16} />
              </button>
            </div>
          ))}
        </div>
      )}
      <Toast text={toast} />
    </div>
  )
}
