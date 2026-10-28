import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import {
  ArrowLeft,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Clock,
  MapPin,
  Users,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import {
  type ReservationCreate,
  ReservationsService,
  ResourcesService,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { LoadingButton } from "@/components/ui/loading-button"
import { Skeleton } from "@/components/ui/skeleton"
import useCustomToast from "@/hooks/useCustomToast"
import {
  addDays,
  formatDate,
  formatTime,
  formatYmd,
  todayInTimeZone,
} from "@/lib/datetime"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/resources/$resourceId")({
  component: ResourceDetailPage,
  head: () => ({
    meta: [{ title: "资源详情 - NexaSlot" }],
  }),
})

const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
const MAX_SLOTS = 8

function ResourceDetailPage() {
  const { resourceId } = Route.useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const [date, setDate] = useState<string | null>(null)
  const [startIndex, setStartIndex] = useState<number | null>(null)
  const [endIndex, setEndIndex] = useState<number | null>(null)

  const resourceQuery = useQuery({
    queryKey: ["resource", resourceId],
    queryFn: async () =>
      (await ResourcesService.readResource({ path: { resource_id: resourceId } }))
        .data,
  })

  const resource = resourceQuery.data
  const timezone = resource?.timezone ?? "Asia/Shanghai"
  const today = todayInTimeZone(timezone)
  const activeDate = date ?? addDays(today, 1)

  const availabilityQuery = useQuery({
    queryKey: ["availability", resourceId, activeDate],
    queryFn: async () =>
      (
        await ResourcesService.readAvailability({
          path: { resource_id: resourceId },
          query: { date: activeDate },
        })
      ).data,
    enabled: Boolean(resource),
  })

  const rulesQuery = useQuery({
    queryKey: ["opening-rules", resourceId],
    queryFn: async () =>
      (
        await ResourcesService.readOpeningRules({
          path: { resource_id: resourceId },
        })
      ).data,
    enabled: Boolean(resource),
  })

  const slots = availabilityQuery.data?.slots ?? []

  useEffect(() => {
    setStartIndex(null)
    setEndIndex(null)
  }, [activeDate])

  const selection = useMemo(() => {
    if (startIndex === null || endIndex === null) {
      return null
    }
    const first = Math.min(startIndex, endIndex)
    const last = Math.max(startIndex, endIndex)
    return { first, last, start: slots[first], end: slots[last] }
  }, [startIndex, endIndex, slots])

  const durationMinutes =
    selection && selection.start && selection.end
      ? Math.round(
          (new Date(selection.end.end_at).getTime() -
            new Date(selection.start.start_at).getTime()) /
            60000,
        )
      : 0

  const handleSlotClick = (index: number) => {
    const slot = slots[index]
    if (!slot || slot.state !== "AVAILABLE") {
      return
    }
    if (startIndex === null || endIndex === null) {
      setStartIndex(index)
      setEndIndex(index)
      return
    }
    const first = Math.min(startIndex, endIndex)
    const last = Math.max(startIndex, endIndex)
    if (index === startIndex && index === endIndex) {
      setStartIndex(null)
      setEndIndex(null)
      return
    }
    const targetFirst = index < first ? index : first
    const targetLast = index > last ? index : last
    const range = slots.slice(targetFirst, targetLast + 1)
    if (range.some((item) => item.state !== "AVAILABLE")) {
      setStartIndex(index)
      setEndIndex(index)
      return
    }
    if (targetLast - targetFirst + 1 > MAX_SLOTS) {
      showErrorToast("单次预约最长 240 分钟")
      return
    }
    setStartIndex(targetFirst)
    setEndIndex(targetLast)
  }

  const createMutation = useMutation({
    mutationFn: async (payload: ReservationCreate) =>
      (
        await ReservationsService.createReservationEndpoint({
          body: payload,
          headers: { "Idempotency-Key": crypto.randomUUID() },
        })
      ).data,
    onSuccess: async (reservation) => {
      showSuccessToast(
        `预约成功：${formatDate(reservation.start_at, timezone)} ${formatTime(
          reservation.start_at,
          timezone,
        )}`,
      )
      await queryClient.invalidateQueries({ queryKey: ["reservations"] })
      await queryClient.invalidateQueries({ queryKey: ["availability"] })
      await navigate({ to: "/reservations" })
    },
    onError: (error) => {
      handleError.call(showErrorToast, error as Error)
      void availabilityQuery.refetch()
    },
  })

  if (resourceQuery.isLoading) {
    return <Skeleton className="h-72 w-full" />
  }

  if (!resource) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-muted-foreground">
          资源不存在或无权访问。
        </CardContent>
      </Card>
    )
  }

  const availableCount = slots.filter((slot) => slot.state === "AVAILABLE").length

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2">
          <Link to="/">
            <ArrowLeft className="mr-1 size-4" />
            返回资源中心
          </Link>
        </Button>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{resource.name}</h1>
            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
              <span className="flex items-center gap-1">
                <MapPin className="size-4" />
                {resource.site_name}
              </span>
              <span className="flex items-center gap-1">
                <Users className="size-4" />
                可容纳 {resource.capacity} 人
              </span>
            </div>
          </div>
          <Badge variant={resource.status === "ACTIVE" ? "default" : "secondary"}>
            {resource.status === "ACTIVE" ? "可预约" : "已停用"}
          </Badge>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <div className="flex flex-col gap-4">
          <Card className="gap-3 py-5">
            <CardHeader className="px-5">
              <CardTitle className="text-base">资源信息</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 px-5 text-sm">
              {resource.description ? (
                <p className="text-muted-foreground">{resource.description}</p>
              ) : null}
              <div className="flex flex-wrap gap-1.5">
                {resource.features.length === 0 ? (
                  <span className="text-xs text-muted-foreground">暂无设备标签</span>
                ) : (
                  resource.features.map((feature) => (
                    <span
                      key={feature}
                      className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                    >
                      {feature}
                    </span>
                  ))
                )}
              </div>
              <div className="rounded-lg bg-muted/60 p-3 text-xs leading-relaxed text-muted-foreground">
                单次 30～240 分钟 · 最晚提前 15 分钟 · 可约未来 14 天 · 开始前 30
                分钟可取消
              </div>
            </CardContent>
          </Card>

          <Card className="gap-3 py-5">
            <CardHeader className="px-5">
              <CardTitle className="text-base">每周开放时间</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5 px-5 text-sm">
              {(rulesQuery.data?.data ?? []).length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  管理员尚未设置开放时间
                </p>
              ) : (
                (rulesQuery.data?.data ?? []).map((rule) => (
                  <div key={rule.id} className="flex justify-between gap-3">
                    <span className="text-muted-foreground">
                      {WEEKDAYS[rule.weekday]}
                    </span>
                    <span>
                      {rule.start_time.slice(0, 5)} - {rule.end_time.slice(0, 5)}
                    </span>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="py-5">
          <CardHeader className="gap-3 px-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base">选择预约时段</CardTitle>
                <CardDescription>
                  {formatYmd(activeDate)} · 共{" "}
                  {availableCount} 个可约时段
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="icon"
                  disabled={activeDate <= today}
                  onClick={() => setDate(addDays(activeDate, -1))}
                >
                  <ChevronLeft className="size-4" />
                </Button>
                <div className="flex items-center gap-2 text-sm">
                  <CalendarDays className="size-4 text-muted-foreground" />
                  <input
                    type="date"
                    className="rounded-md border bg-background px-2 py-1 text-sm"
                    value={activeDate}
                    min={today}
                    max={addDays(today, 14)}
                    onChange={(event) => setDate(event.target.value)}
                  />
                </div>
                <Button
                  variant="outline"
                  size="icon"
                  disabled={activeDate >= addDays(today, 14)}
                  onClick={() => setDate(addDays(activeDate, 1))}
                >
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="px-5">
            {availabilityQuery.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : slots.length === 0 ? (
              <div className="rounded-lg border border-dashed py-12 text-center text-sm text-muted-foreground">
                当天没有开放时段
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
                {slots.map((slot, index) => {
                  const selected =
                    selection !== null &&
                    index >= selection.first &&
                    index <= selection.last
                  const disabled = slot.state !== "AVAILABLE"
                  return (
                    <button
                      key={slot.start_at}
                      type="button"
                      disabled={disabled}
                      onClick={() => handleSlotClick(index)}
                      className={[
                        "flex flex-col items-center justify-center rounded-lg border px-2 py-2 text-sm transition",
                        selected
                          ? "border-primary bg-primary text-primary-foreground shadow-sm"
                          : disabled
                            ? slot.state === "BOOKED"
                              ? "cursor-not-allowed border-border bg-muted/60 text-muted-foreground line-through"
                              : "cursor-not-allowed border-dashed bg-muted/30 text-muted-foreground"
                            : "border-border bg-background hover:border-primary/60 hover:bg-primary/5",
                      ].join(" ")}
                    >
                      <span className="font-medium">
                        {formatTime(slot.start_at, timezone)}
                      </span>
                      <span className="text-[10px] opacity-80">
                        {slot.state === "AVAILABLE"
                          ? "可预约"
                          : slot.state === "BOOKED"
                            ? "已预约"
                            : slot.state === "CLOSED"
                              ? "不开放"
                              : "已结束"}
                      </span>
                    </button>
                  )
                })}
              </div>
            )}

            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted/50 px-4 py-3">
              <div className="flex items-center gap-2 text-sm">
                <Clock className="size-4 text-muted-foreground" />
                {selection && selection.start && selection.end ? (
                  <span>
                    {formatTime(selection.start.start_at, timezone)} -{" "}
                    {formatTime(selection.end.end_at, timezone)} ·{" "}
                    {durationMinutes} 分钟
                  </span>
                ) : (
                  <span className="text-muted-foreground">请选择连续时段</span>
                )}
              </div>
              <LoadingButton
                loading={createMutation.isPending}
                disabled={
                  !selection ||
                  durationMinutes < 30 ||
                  durationMinutes > 240 ||
                  resource.status !== "ACTIVE"
                }
                onClick={() => {
                  if (!selection || !selection.start || !selection.end) return
                  createMutation.mutate({
                    resource_id: resource.id,
                    start_at: selection.start.start_at,
                    end_at: selection.end.end_at,
                  })
                }}
              >
                提交预约
              </LoadingButton>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
