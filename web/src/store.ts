import { create } from 'zustand'
import { api } from './api'

export interface FamilyItem {
  id: number
  name: string
  slug: string
  surname?: string
  visibility: number
  role: 'admin' | 'member'
}

export interface UserInfo {
  id: number
  username: string
  real_name: string
  phone?: string
  email?: string
  is_superuser: boolean
  must_change_pwd: boolean
  families: FamilyItem[]
  site_name?: string
  page_size?: number
  password_min_length?: number
  password_require_strong?: boolean
  default_strategy?: string
  upload_max_mb?: number
}

interface State {
  user: UserInfo | null
  familyId: number | null
  loaded: boolean
  dark: boolean
  recentFamilyIds: number[]
  load: () => Promise<void>
  setFamily: (id: number) => void
  toggleDark: () => void
  clear: () => void
}

function recentIds(userId: number, allowed: FamilyItem[], current?: number): number[] {
  let stored: number[] = []
  try {
    const value = JSON.parse(localStorage.getItem(`fts_recent_${userId}`) || '[]')
    if (Array.isArray(value)) stored = value.filter(v => Number.isInteger(v))
  } catch { /* 无效历史只影响便利入口 */ }
  const ids = [...new Set([...(current ? [current] : []), ...stored])]
    .filter(id => allowed.some(f => f.id === id)).slice(0, 8)
  localStorage.setItem(`fts_recent_${userId}`, JSON.stringify(ids))
  return ids
}

export const useStore = create<State>((set, get) => ({
  user: null,
  familyId: Number(localStorage.getItem('fts_family') || 0) || null,
  loaded: false,
  dark: localStorage.getItem('fts_theme') === 'dark',
  recentFamilyIds: [],
  load: async () => {
    try {
      const user = await api.get<UserInfo>('/api/auth/me')
      let fid = Number(localStorage.getItem(`fts_family_${user.id}`) || localStorage.getItem('fts_family') || 0)
      if (!user.families.some((f) => f.id === fid)) {
        fid = user.families[0]?.id || 0
        localStorage.setItem('fts_family', String(fid))
      }
      set({ user, familyId: fid || null, recentFamilyIds: recentIds(user.id, user.families, fid), loaded: true })
    } catch {
      set({ user: null, familyId: null, recentFamilyIds: [], loaded: true })
    }
  },
  setFamily: (id) => {
    const user = get().user
    if (!user?.families.some(f => f.id === id)) return
    localStorage.setItem('fts_family', String(id))
    localStorage.setItem(`fts_family_${user.id}`, String(id))
    set({ familyId: id, recentFamilyIds: recentIds(user.id, user.families, id) })
  },
  toggleDark: () => set((state) => {
    const dark = !state.dark
    localStorage.setItem('fts_theme', dark ? 'dark' : 'light')
    return { dark }
  }),
  clear: () => {
    localStorage.removeItem('fts_family')
    set({ user: null, familyId: null, recentFamilyIds: [] })
  },
}))

export function currentFamily(): FamilyItem | undefined {
  const { user, familyId } = useStore.getState()
  return user?.families.find((f) => f.id === familyId)
}

export function isFamilyAdmin(): boolean {
  const f = currentFamily()
  return !!f && (f.role === 'admin' || !!useStore.getState().user?.is_superuser)
}

export function isMobile(): boolean {
  return typeof window !== 'undefined' && window.innerWidth < 768
}
