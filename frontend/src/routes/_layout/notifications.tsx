import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Bell, CheckCheck } from "lucide-react"

import { NotificationsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import useCustomToast from "@/hooks/useCustomToast"
import { formatDateTime } from "@/lib/datetime"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/notifications")({
  component: NotificationsPage,
  head: () => ({
    meta: [{ title: "通知中心 - NexaSlot" }],
  }),
})

function NotificationsPage() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { data, isLoading } = useQuery({
    queryKey: ["notifications"],
    queryFn: async () =>
      (
        await NotificationsService.readNotifications({
          query: { page: 1, page_size: 100 },
        })
      ).data,
    refetchInterval: 20_000,
  })

  const markRead = useMutation({
    mutationFn: async (notificationId: string) =>
      (
        await NotificationsService.markNotificationRead({
          path: { notification_id: notificationId },
        })
      ).data,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["notifications"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const markAll = useMutation({
    mutationFn: async () =>
      (await NotificationsService.markAllNotificationsRead()).data,
    onSuccess: async () => {
      showSuccessToast("全部通知已标记为已读")
      await queryClient.invalidateQueries({ queryKey: ["notifications"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const unread = data?.unread_count ?? 0

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            通知中心
            {unread > 0 ? <Badge>{unread} 条未读</Badge> : null}
          </h1>
          <p className="text-sm text-muted-foreground">
            预约、取消、候补名额与过期提醒；断线后仍可在这里补齐。
          </p>
        </div>
        <Button
          variant="outline"
          disabled={unread === 0 || markAll.isPending}
          onClick={() => markAll.mutate()}
        >
          <CheckCheck className="size-4" />
          全部已读
        </Button>
      </div>

      {isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : (data?.data.length ?? 0) === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-14 text-center">
            <Bell className="size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">暂无通知</p>
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {data?.data.map((notification) => {
            const unreadItem = notification.read_at === null
            return (
              <Card
                key={notification.id}
                className={
                  unreadItem
                    ? "border-primary/30 bg-primary/[0.03] py-4"
                    : "py-4"
                }
              >
                <CardContent className="flex flex-wrap items-start justify-between gap-4 px-5">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">
                        {notification.title}
                      </span>
                      {unreadItem ? (
                        <Badge variant="secondary">未读</Badge>
                      ) : null}
                      <span className="text-xs text-muted-foreground">
                        {notification.type}
                      </span>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {notification.message}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatDateTime(notification.created_at, "Asia/Shanghai")}
                    </p>
                  </div>
                  {unreadItem ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={markRead.isPending}
                      onClick={() => markRead.mutate(notification.id)}
                    >
                      标记已读
                    </Button>
                  ) : null}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
