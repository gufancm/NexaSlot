import {
  Bell,
  CalendarClock,
  CalendarDays,
  LayoutDashboard,
  LibraryBig,
  Settings2,
  Sparkles,
  Users,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { useOrg } from "@/hooks/useOrg"
import { type Item, Main } from "./Main"
import { User } from "./User"

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const { canManageResources, isAdmin } = useOrg()

  const items: Item[] = [
    { icon: LibraryBig, title: "资源中心", path: "/" },
    { icon: Sparkles, title: "智能匹配", path: "/match" },
    { icon: CalendarDays, title: "我的预约", path: "/reservations" },
    { icon: CalendarClock, title: "我的候补", path: "/waitlist" },
    { icon: Bell, title: "通知中心", path: "/notifications" },
  ]

  if (isAdmin) {
    items.push({ icon: LayoutDashboard, title: "数据看板", path: "/dashboard" })
  }
  if (canManageResources) {
    items.push({ icon: Settings2, title: "管理后台", path: "/admin" })
  }
  if (currentUser?.is_superuser) {
    items.push({ icon: Users, title: "平台用户", path: "/users" })
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:items-center group-data-[collapsible=icon]:px-0">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
