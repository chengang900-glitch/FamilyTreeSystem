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
}

interface State {
  user: UserInfo | null
  familyId: number | null
  loaded: boolean
  load: () => Promise<void>
  setFamily: (id: number) => void
  clear: () => void
}

export const useStore = create<State>((set) => ({
  user: null,
  familyId: Number(localStorage.getItem('fts_family') || 0) || null,
  loaded: false,
  load: async () => {
    try {
      const user = await api.get<UserInfo>('/api/auth/me')
      let fid = Number(localStorage.getItem('fts_family') || 0)
      if (!user.families.some((f) => f.id === fid)) {
        fid = user.families[0]?.id || 0
        localStorage.setItem('fts_family', String(fid))
      }
      set({ user, familyId: fid || null, loaded: true })
    } catch {
      set({ user: null, loaded: true })
    }
  },
  setFamily: (id) => {
    localStorage.setItem('fts_family', String(id))
    set({ familyId: id })
  },
  clear: () => {
    localStorage.removeItem('fts_family')
    set({ user: null, familyId: null })
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
