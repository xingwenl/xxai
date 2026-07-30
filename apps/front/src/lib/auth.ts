import { useNavigate } from '@tanstack/react-router'
import { useAuthStore } from '@/stores/auth-store'

export function logout() {
  useAuthStore.getState().auth.reset()
  const navigate = useNavigate()

  // Preserve current location for redirect after sign-in
  const currentPath = location.href
  navigate({
    to: '/sign-in',
    search: { redirect: currentPath },
    replace: true,
  })
}
