import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { CalendarX2, Clock, MapPin } from "lucide-react"
import { useState } from "react"

import {
  type ReservationPublic,
  ReservationsService,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { formatDateTime, formatRange } from "@/lib/datetime"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/reservations")({
  component: MyReservationsPage,
  head: () => ({
    meta: [{ title: "我的预约 - NexaSlot" }],
  }),
})

function MyReservationsPage() {
  const [scope, setScope] = useState<"upcoming" | "history">("upcoming")
  const [target, setTarget] = useState<ReservationPublic | null>(null)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const { data, isLoading } = useQuery({
    queryKey: ["reservations", "me", scope],
    queryFn: async () =>
      (
        await ReservationsService.readMyReservations({
          query: { scope, page: 1, page_size: 50 },
        })
      ).data,
  })

  const cancelMutation = useMutation({
    mutationFn: async (reservationId: string) =>
      (
        await ReservationsService.cancelReservationEndpoint({
          path: { reservation_id: reservationId },
        })
      ).data,
    onSuccess: async () => {
      showSuccessToast("预约已取消，时段已释放")
      setTarget(null)
      await queryClient.invalidateQueries({ queryKey: ["reservations"] })
      await queryClient.invalidateQueries({ queryKey: ["availability"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const reservations = data?.data ?? []

  const renderList = () => {
    if (isLoading) {
      return (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-28 w-full" />
          ))}
        </div>
      )
    }
    if (reservations.length === 0) {
      return (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <div className="grid size-12 place-items-center rounded-full bg-muted">
              <CalendarX2 className="size-6 text-muted-foreground" />
            </div>
            <h2 className="text-lg font-semibold">
              {scope === "upcoming" ? "还没有即将开始的预约" : "暂无历史预约"}
            </h2>
            <p className="text-sm text-muted-foreground">
              去资源中心挑选一个时间和会议室吧。
            </p>
            <Button asChild variant="outline">
              <Link to="/">浏览资源</Link>
            </Button>
          </CardContent>
        </Card>
      )
    }
    return (
      <div className="flex flex-col gap-3">
        {reservations.map((reservation) => {
          const cancelled = reservation.status === "CANCELLED"
          return (
            <Card key={reservation.id} className="py-4">
              <CardContent className="flex flex-wrap items-center justify-between gap-4 px-5">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-base font-semibold">
                      {reservation.resource_name}
                    </span>
                    <Badge variant={cancelled ? "secondary" : "default"}>
                      {cancelled ? "已取消" : "已确认"}
                    </Badge>
                  </div>
                  <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
                    <Clock className="size-4" />
                    {formatRange(
                      reservation.start_at,
                      reservation.end_at,
                      reservation.timezone,
                    )}
                  </p>
                  <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                    <MapPin className="size-3.5" />
                    {reservation.site_name} · 下单于{" "}
                    {formatDateTime(reservation.created_at, reservation.timezone)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {reservation.can_cancel ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setTarget(reservation)}
                    >
                      取消预约
                    </Button>
                  ) : null}
                  <Button variant="ghost" size="sm" asChild>
                    <Link
                      to="/resources/$resourceId"
                      params={{ resourceId: reservation.resource_id }}
                    >
                      查看资源
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">我的预约</h1>
        <p className="text-sm text-muted-foreground">
          查看即将开始的预约与历史记录，开始前 30 分钟可取消
        </p>
      </div>

      <Tabs
        value={scope}
        onValueChange={(value) => setScope(value as "upcoming" | "history")}
      >
        <TabsList>
          <TabsTrigger value="upcoming">即将开始</TabsTrigger>
          <TabsTrigger value="history">历史记录</TabsTrigger>
        </TabsList>
        <TabsContent value="upcoming" className="mt-4">
          {scope === "upcoming" ? renderList() : null}
        </TabsContent>
        <TabsContent value="history" className="mt-4">
          {scope === "history" ? renderList() : null}
        </TabsContent>
      </Tabs>

      <Dialog open={target !== null} onOpenChange={(open) => !open && setTarget(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>取消这笔预约？</DialogTitle>
            <DialogDescription>
              {target
                ? `${target.resource_name} · ${formatRange(
                    target.start_at,
                    target.end_at,
                    target.timezone,
                  )}`
                : ""}
              <br />
              取消后时段会立即释放，其他用户可以重新预约。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTarget(null)}>
              保留
            </Button>
            <LoadingButton
              variant="destructive"
              loading={cancelMutation.isPending}
              onClick={() => target && cancelMutation.mutate(target.id)}
            >
              确认取消
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
