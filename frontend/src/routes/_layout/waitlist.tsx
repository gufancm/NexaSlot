import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { CalendarClock, Check, Clock, MapPin, Timer, X } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { type WaitlistEntryPublic, WaitlistService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { LoadingButton } from "@/components/ui/loading-button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { formatDateTime, formatRange } from "@/lib/datetime"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/waitlist")({
  component: WaitlistPage,
  head: () => ({
    meta: [{ title: "我的候补 - NexaSlot" }],
  }),
})

const STATUS_LABEL: Record<string, string> = {
  WAITING: "排队中",
  OFFERED: "待确认",
  CONFIRMED: "已转为预约",
  EXPIRED: "已过期",
  DECLINED: "已拒绝",
  CANCELLED: "已退出",
}

function useNow() {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

function OfferCountdown({ expiresAt }: { expiresAt: string }) {
  const now = useNow()
  const remaining = Math.max(0, new Date(expiresAt).getTime() - now)
  const minutes = Math.floor(remaining / 60000)
  const seconds = Math.floor((remaining % 60000) / 1000)
  if (remaining <= 0) {
    return (
      <span className="text-destructive">已到确认截止时间，等待服务端顺延</span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 font-medium text-amber-700 dark:text-amber-300">
      <Timer className="size-4" />
      剩余 {minutes.toString().padStart(2, "0")}:
      {seconds.toString().padStart(2, "0")}
    </span>
  )
}

function WaitlistPage() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { data, isLoading } = useQuery({
    queryKey: ["waitlist", "me"],
    queryFn: async () =>
      (
        await WaitlistService.readMyWaitlist({
          query: { page: 1, page_size: 100 },
        })
      ).data,
    refetchInterval: 15_000,
  })

  const confirmMutation = useMutation({
    mutationFn: async (holdId: string) =>
      (
        await WaitlistService.confirmOfferEndpoint({
          path: { hold_id: holdId },
        })
      ).data,
    onSuccess: async (reservation) => {
      showSuccessToast(`候补已确认：${reservation.resource_name}`)
      await queryClient.invalidateQueries({ queryKey: ["waitlist"] })
      await queryClient.invalidateQueries({ queryKey: ["reservations"] })
      await queryClient.invalidateQueries({ queryKey: ["availability"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const declineMutation = useMutation({
    mutationFn: async (holdId: string) =>
      (
        await WaitlistService.declineOfferEndpoint({
          path: { hold_id: holdId },
        })
      ).data,
    onSuccess: async () => {
      showSuccessToast("已拒绝本次候补名额，系统会顺延给下一位")
      await queryClient.invalidateQueries({ queryKey: ["waitlist"] })
      await queryClient.invalidateQueries({ queryKey: ["availability"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const leaveMutation = useMutation({
    mutationFn: async (entryId: string) =>
      (
        await WaitlistService.leaveWaitlistEndpoint({
          path: { entry_id: entryId },
        })
      ).data,
    onSuccess: async () => {
      showSuccessToast("已退出候补")
      await queryClient.invalidateQueries({ queryKey: ["waitlist"] })
      await queryClient.invalidateQueries({ queryKey: ["availability"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const entries = useMemo(() => data?.data ?? [], [data])
  const active = entries.filter(
    (entry) => entry.status === "WAITING" || entry.status === "OFFERED",
  )
  const history = entries.filter(
    (entry) => entry.status !== "WAITING" && entry.status !== "OFFERED",
  )

  const renderList = (items: WaitlistEntryPublic[], emptyText: string) => {
    if (items.length === 0) {
      return (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-14 text-center">
            <CalendarClock className="size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">{emptyText}</p>
            <Button asChild variant="outline">
              <Link to="/">浏览资源</Link>
            </Button>
          </CardContent>
        </Card>
      )
    }
    return (
      <div className="flex flex-col gap-3">
        {items.map((entry) => {
          const offer = entry.hold
          const offered =
            entry.status === "OFFERED" && offer?.status === "ACTIVE"
          return (
            <Card
              key={entry.id}
              className={
                offered
                  ? "border-amber-400/70 bg-amber-50/50 py-4 dark:bg-amber-950/20"
                  : "py-4"
              }
            >
              <CardContent className="flex flex-wrap items-start justify-between gap-4 px-5">
                <div className="min-w-0 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-base font-semibold">
                      {entry.resource_name}
                    </span>
                    <Badge variant={offered ? "default" : "secondary"}>
                      {STATUS_LABEL[entry.status] ?? entry.status}
                    </Badge>
                    {entry.queue_position ? (
                      <span className="text-xs text-muted-foreground">
                        排队第 {entry.queue_position} 位
                      </span>
                    ) : null}
                  </div>
                  <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                    <Clock className="size-4" />
                    {formatRange(entry.start_at, entry.end_at, entry.timezone)}
                  </p>
                  <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <MapPin className="size-3.5" />
                    {entry.site_name} · 加入于{" "}
                    {formatDateTime(entry.created_at, entry.timezone)}
                  </p>
                  {offered && offer ? (
                    <div className="flex flex-col gap-1 pt-1 text-sm">
                      <OfferCountdown expiresAt={offer.expires_at} />
                      <span className="text-xs text-muted-foreground">
                        截止 {formatDateTime(offer.expires_at, entry.timezone)}
                      </span>
                    </div>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {offered && offer ? (
                    <>
                      <LoadingButton
                        size="sm"
                        loading={confirmMutation.isPending}
                        onClick={() => confirmMutation.mutate(offer.id)}
                      >
                        <Check className="size-4" />
                        确认预约
                      </LoadingButton>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={declineMutation.isPending}
                        onClick={() => declineMutation.mutate(offer.id)}
                      >
                        <X className="size-4" />
                        放弃名额
                      </Button>
                    </>
                  ) : entry.status === "WAITING" ? (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={leaveMutation.isPending}
                      onClick={() => leaveMutation.mutate(entry.id)}
                    >
                      退出候补
                    </Button>
                  ) : null}
                  <Button variant="ghost" size="sm" asChild>
                    <Link
                      to="/resources/$resourceId"
                      params={{ resourceId: entry.resource_id }}
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
        <h1 className="text-2xl font-bold tracking-tight">我的候补</h1>
        <p className="text-sm text-muted-foreground">
          候补按同资源、完全相同时段的加入顺序排队；名额释放后会为你保留 10
          分钟确认时间。
        </p>
      </div>

      {isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : (
        <Tabs defaultValue="active">
          <TabsList>
            <TabsTrigger value="active">进行中 ({active.length})</TabsTrigger>
            <TabsTrigger value="history">历史 ({history.length})</TabsTrigger>
          </TabsList>
          <TabsContent value="active" className="mt-4">
            {renderList(active, "暂无进行中的候补")}
          </TabsContent>
          <TabsContent value="history" className="mt-4">
            {renderList(history, "暂无候补历史")}
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}
