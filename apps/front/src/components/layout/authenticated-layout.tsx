import { useEffect } from 'react'
import { Navigate, Outlet } from '@tanstack/react-router'
import { getCurrentUser } from '@/api/user'
import { useAuthStore } from '@/stores/auth-store'
import { getCookie } from '@/lib/cookies'
import { cn } from '@/lib/utils'
import { LayoutProvider } from '@/context/layout-provider'
import { SearchProvider } from '@/context/search-provider'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/layout/app-sidebar'
import { SkipToMain } from '@/components/skip-to-main'
import { AgentNavigationBridge } from '@/features/agent-navigation/agent-navigation-bridge'

type AuthenticatedLayoutProps = {
  children?: React.ReactNode
}

export function AuthenticatedLayout({ children }: AuthenticatedLayoutProps) {
  const defaultOpen = getCookie('sidebar_state') !== 'false'
  const { auth } = useAuthStore()

  useEffect(() => {
    if (!auth.accessToken) return
    if (auth.user) return
    getCurrentUser()
      .then((u) => {
        if (u) auth.setUser(u)
        else auth.reset()
      })
      .catch(() => {
        auth.reset()
      })
  }, [auth])

  if (!auth.accessToken) {
    return <Navigate to='/sign-in' replace />
  }

  return (
    <SearchProvider>
      <LayoutProvider>
        <SidebarProvider defaultOpen={defaultOpen}>
          <SkipToMain />
          <AppSidebar />
          <SidebarInset
            className={cn(
              // Set content container, so we can use container queries
              '@container/content',

              // If layout is fixed, set the height
              // to 100svh to prevent overflow
              'has-data-[layout=fixed]:h-svh',

              // If layout is fixed and sidebar is inset,
              // set the height to 100svh - spacing (total margins) to prevent overflow
              'peer-data-[variant=inset]:has-data-[layout=fixed]:h-[calc(100svh-(var(--spacing)*4))]'
            )}
          >
            {children ?? <Outlet />}
          </SidebarInset>
          <AgentNavigationBridge />
        </SidebarProvider>
      </LayoutProvider>
    </SearchProvider>
  )
}
