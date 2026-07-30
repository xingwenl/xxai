import { create } from 'zustand'

const ACCESS_TOKEN = 'chat_token'

export interface AuthUser {
  id: number
  name: string
  email: string
  account: string
  is_active: boolean
  roles: Array<{
    id: number
    name: string
    code: string
  }>
}

interface AuthState {
  auth: {
    user: AuthUser | null
    setUser: (user: AuthUser | null) => void
    accessToken: string
    setAccessToken: (accessToken: string) => void
    resetAccessToken: () => void
    reset: () => void
  }
}

export const useAuthStore = create<AuthState>()((set) => {
  const initToken =
    typeof localStorage !== 'undefined'
      ? (localStorage.getItem(ACCESS_TOKEN) ?? '')
      : ''
  return {
    auth: {
      user: null,
      setUser: (user) =>
        set((state) => ({ ...state, auth: { ...state.auth, user } })),
      accessToken: initToken,
      setAccessToken: (accessToken) =>
        set((state) => {
          if (typeof localStorage !== 'undefined') {
            localStorage.setItem(ACCESS_TOKEN, accessToken)
          }
          return { ...state, auth: { ...state.auth, accessToken } }
        }),
      resetAccessToken: () =>
        set((state) => {
          if (typeof localStorage !== 'undefined') {
            localStorage.removeItem(ACCESS_TOKEN)
          }
          return { ...state, auth: { ...state.auth, accessToken: '' } }
        }),
      reset: () =>
        set((state) => {
          if (typeof localStorage !== 'undefined') {
            localStorage.removeItem(ACCESS_TOKEN)
          }
          return {
            ...state,
            auth: { ...state.auth, user: null, accessToken: '' },
          }
        }),
    },
  }
})
