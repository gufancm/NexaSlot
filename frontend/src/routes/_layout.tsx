import { useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"
import { Building2 } from "lucide-react"

import { Footer } from "@/components/Common/Footer"
import { NotificationBell } from "@/components/Common/NotificationBell"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"
import { OrgProvider, useOrg } from "@/hooks/useOrg"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

function Layout() {
  return (
    <OrgProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>
          <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 border-b bg-background px-4">
            <SidebarTrigger className="-ml-1 text-muted-foreground" />
            <div className="ml-2">
              <OrgSwitcher />
            </div>
            <div className="ml-auto">
              <NotificationBell />
            </div>
          </header>
          <main className="flex-1 p-6 md:p-8">
            <div className="mx-auto max-w-7xl">
              <Outlet />
            </div>
          </main>
          <Footer />
        </SidebarInset>
      </SidebarProvider>
    </OrgProvider>
  )
}

function OrgSwitcher() {
  const { organizations, currentOrg, currentOrgId, setCurrentOrgId } = useOrg()
  const queryClient = useQueryClient()

  if (organizations.length === 0) {
    return (
      <span className="text-sm text-muted-foreground">尚未加入任何组织</span>
    )
  }

  if (organizations.length === 1 && currentOrg) {
    return (
      <div className="flex h-9 items-center gap-2 rounded-md border bg-muted/40 px-3 text-sm">
        <Building2 className="size-4 text-muted-foreground" />
        <span className="font-medium">{currentOrg.name}</span>
      </div>
    )
  }

  return (
    <Select
      value={currentOrgId ?? undefined}
      onValueChange={(value) => {
        setCurrentOrgId(value)
        void queryClient.invalidateQueries()
      }}
    >
      <SelectTrigger className="h-9 w-full min-w-48 max-w-xs gap-2">
        <Building2 className="size-4 text-muted-foreground" />
        <SelectValue placeholder={currentOrg?.name ?? "选择组织"} />
      </SelectTrigger>
      <SelectContent>
        {organizations.map((org) => (
          <SelectItem key={org.id} value={org.id}>
            {org.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
