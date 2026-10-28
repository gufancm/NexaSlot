import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Bell } from "lucide-react"

import { NotificationsService } from "@/client"
import { Button } from "@/components/ui/button"

export function NotificationBell() {
  const { data } = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: async () =>
      (
        await NotificationsService.readNotifications({
          query: { page: 1, page_size: 1, unread_only: true },
        })
      ).data,
    refetchInterval: 30_000,
  })
  const unread = data?.unread_count ?? 0

  return (
    <Button variant="ghost" size="icon" asChild className="relative">
      <Link to="/notifications" aria-label="通知中心">
        <Bell className="size-5" />
        {unread > 0 ? (
          <span className="absolute -right-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full bg-primary px-1 text-[10px] font-semibold leading-4 text-primary-foreground">
            {unread > 99 ? "99+" : unread}
          </span>
        ) : null}
      </Link>
    </Button>
  )
}
