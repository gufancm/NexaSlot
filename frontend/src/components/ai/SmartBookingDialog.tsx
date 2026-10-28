import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  Bot,
  CalendarDays,
  CheckCircle2,
  Clock,
  MapPin,
  RefreshCw,
  Sparkles,
  Users,
  Wand2,
  Wrench,
} from "lucide-react"
import { useState } from "react"

import {
  type AIRecommendPublic,
  AiService,
  type BookingOverrides,
  type BookingSuggestion,
  type InterpretedBooking,
  ReservationsService,
  SitesService,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { useOrg } from "@/hooks/useOrg"
import { formatRange } from "@/lib/datetime"
import { handleError } from "@/utils"

const EXAMPLES = [
  "明天下午，8个人，带投影仪，开两个小时",
  "后天上午10点到12点，6个人，要白板",
  "下周三下午3点开一小时，4个人，二楼",
]

const FIELD_LABELS: Record<string, string> = {
  booking_request: "预约需求",
  resource_type: "资源类型",
  date: "日期",
  party_size: "人数",
  duration_minutes: "时长",
  time_window_start: "开始时间",
  time_window_end: "结束时间",
  site_id: "场地",
}

function shortTime(value?: string | null): string {
  return value ? value.slice(0, 5) : ""
}

function errorStatus(error: unknown): number | undefined {
  if (typeof error === "object" && error !== null && "response" in error) {
    return (error as { response?: { status?: number } }).response?.status
  }
  return undefined
}

export function SmartBookingDialog() {
  const { currentOrgId } = useOrg()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState("")
  const [siteId, setSiteId] = useState("all")
  const [result, setResult] = useState<AIRecommendPublic | null>(null)
  const [selected, setSelected] = useState<BookingSuggestion | null>(null)
  const [idempotencyKey, setIdempotencyKey] = useState("")
  const [confirmed, setConfirmed] = useState<{
    id: string
    resourceName: string
    startAt: string
    endAt: string
  } | null>(null)
  const [conflict, setConflict] = useState(false)
  const [overrideDate, setOverrideDate] = useState("")
  const [overrideStart, setOverrideStart] = useState("")
  const [overrideEnd, setOverrideEnd] = useState("")
  const [overrideDuration, setOverrideDuration] = useState("")
  const [overrideParty, setOverrideParty] = useState("")
  const [overrideEquipment, setOverrideEquipment] = useState("")
  const [overrideFloor, setOverrideFloor] = useState("")

  const sitesQuery = useQuery({
    queryKey: ["sites", currentOrgId],
    queryFn: async () =>
      (await SitesService.readSites({ path: { org_id: currentOrgId! } })).data,
    enabled: open && Boolean(currentOrgId),
  })

  const syncOverrides = (interpreted?: InterpretedBooking) => {
    setOverrideDate(interpreted?.date ?? "")
    setOverrideStart(shortTime(interpreted?.time_window_start))
    setOverrideEnd(shortTime(interpreted?.time_window_end))
    setOverrideDuration(
      interpreted?.duration_minutes ? String(interpreted.duration_minutes) : "",
    )
    setOverrideParty(
      interpreted?.party_size ? String(interpreted.party_size) : "",
    )
    setOverrideEquipment((interpreted?.required_equipment ?? []).join("、"))
    setOverrideFloor(
      interpreted?.preferred_floor !== null &&
        interpreted?.preferred_floor !== undefined
        ? String(interpreted.preferred_floor)
        : "",
    )
  }

  const chooseSuggestion = (suggestion: BookingSuggestion) => {
    setSelected(suggestion)
    setIdempotencyKey(crypto.randomUUID())
    setConfirmed(null)
    setConflict(false)
  }

  const recommendMutation = useMutation({
    mutationFn: async (overrides?: BookingOverrides) =>
      (
        await AiService.recommendBookingEndpoint({
          body: {
            org_id: currentOrgId!,
            message: message.trim(),
            site_id: siteId === "all" ? null : siteId,
            overrides: overrides ?? null,
          },
        })
      ).data,
    onSuccess: (data) => {
      setResult(data)
      setConfirmed(null)
      setConflict(false)
      syncOverrides(data.interpreted)
      const first = data.suggestions?.[0] ?? null
      setSelected(first)
      setIdempotencyKey(first ? crypto.randomUUID() : "")
    },
    onError: handleError.bind(showErrorToast),
  })

  const confirmMutation = useMutation({
    mutationFn: async (suggestion: BookingSuggestion) =>
      (
        await ReservationsService.createReservationEndpoint({
          body: {
            resource_id: suggestion.resource_id,
            start_at: suggestion.start_at,
            end_at: suggestion.end_at,
          },
          headers: { "Idempotency-Key": idempotencyKey || crypto.randomUUID() },
        })
      ).data,
    onSuccess: async (reservation) => {
      setConfirmed({
        id: reservation.id,
        resourceName: reservation.resource_name,
        startAt: reservation.start_at,
        endAt: reservation.end_at,
      })
      setConflict(false)
      showSuccessToast(`预约成功，订单号 ${reservation.id}`)
      await queryClient.invalidateQueries({ queryKey: ["reservations"] })
      await queryClient.invalidateQueries({ queryKey: ["availability"] })
    },
    onError: (error) => {
      if (errorStatus(error) === 409) {
        setConflict(true)
        showErrorToast("该时段刚刚被占用，请重新推荐或选择其他方案")
        return
      }
      handleError.call(showErrorToast, error as Error)
    },
  })

  const submit = (withOverrides: boolean) => {
    if (!currentOrgId || message.trim().length < 2) return
    if (!withOverrides) {
      setResult(null)
      setSelected(null)
      setConfirmed(null)
      setConflict(false)
      recommendMutation.mutate(undefined)
      return
    }
    const overrides: BookingOverrides = {
      date: overrideDate || null,
      time_window_start: overrideStart ? `${overrideStart}:00` : null,
      time_window_end: overrideEnd ? `${overrideEnd}:00` : null,
      duration_minutes: overrideDuration ? Number(overrideDuration) : null,
      party_size: overrideParty ? Number(overrideParty) : null,
      required_equipment: overrideEquipment
        .split(/[，,、\s]+/)
        .map((item) => item.trim())
        .filter(Boolean),
      preferred_floor: overrideFloor ? Number(overrideFloor) : null,
    }
    recommendMutation.mutate(overrides)
  }

  const interpreted = result?.interpreted
  const missingLabels = (result?.missing_fields ?? []).map(
    (field) => FIELD_LABELS[field] ?? field,
  )

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) {
          setConflict(false)
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" className="gap-2">
          <Wand2 className="size-4 text-primary" />
          智能预约
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="grid size-8 place-items-center rounded-lg bg-primary/10">
              <Bot className="size-4 text-primary" />
            </span>
            智能预约助手
          </DialogTitle>
          <DialogDescription>
            用一句话描述需求，系统会解析条件并查询真实可用资源。AI
            只负责理解需求，不会直接创建订单。
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-5">
          <div className="grid gap-2">
            <Label htmlFor="ai-booking-message">预约需求</Label>
            <Textarea
              id="ai-booking-message"
              value={message}
              maxLength={500}
              placeholder="例如：明天下午，8个人，带投影仪，开两个小时"
              onChange={(event) => setMessage(event.target.value)}
            />
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  className="rounded-full border bg-muted/40 px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted"
                  onClick={() => setMessage(example)}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="grid flex-1 gap-2">
              <Label>场地</Label>
              <Select value={siteId} onValueChange={setSiteId}>
                <SelectTrigger>
                  <SelectValue placeholder="自动选择场地" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">自动选择（组织统一时区）</SelectItem>
                  {(sitesQuery.data?.data ?? []).map((site) => (
                    <SelectItem key={site.id} value={site.id}>
                      {site.name} · {site.timezone}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <LoadingButton
              loading={recommendMutation.isPending}
              disabled={message.trim().length < 2}
              onClick={() => submit(false)}
            >
              <Sparkles className="size-4" />
              分析并推荐
            </LoadingButton>
          </div>

          {result ? (
            <div className="flex flex-col gap-4 rounded-xl border bg-muted/20 p-4">
              <div className="flex items-start gap-2">
                {result.status === "suggestions" ? (
                  <CheckCircle2 className="mt-0.5 size-4 text-emerald-600" />
                ) : (
                  <Clock className="mt-0.5 size-4 text-amber-600" />
                )}
                <div className="min-w-0">
                  <p className="text-sm font-medium">{result.message}</p>
                  {missingLabels.length > 0 ? (
                    <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
                      还需要补充：{missingLabels.join("、")}
                    </p>
                  ) : null}
                </div>
              </div>

              {interpreted ? (
                <div className="flex flex-wrap gap-2 text-xs">
                  {interpreted.date ? (
                    <Badge variant="secondary" className="gap-1">
                      <CalendarDays className="size-3" />
                      {interpreted.date}
                    </Badge>
                  ) : null}
                  {interpreted.time_window_start ? (
                    <Badge variant="secondary" className="gap-1">
                      <Clock className="size-3" />
                      {shortTime(interpreted.time_window_start)}
                      {interpreted.time_window_end
                        ? `–${shortTime(interpreted.time_window_end)}`
                        : ""}
                    </Badge>
                  ) : null}
                  {interpreted.duration_minutes ? (
                    <Badge variant="secondary">
                      {interpreted.duration_minutes} 分钟
                    </Badge>
                  ) : null}
                  {interpreted.party_size ? (
                    <Badge variant="secondary" className="gap-1">
                      <Users className="size-3" />
                      {interpreted.party_size} 人
                    </Badge>
                  ) : null}
                  {(interpreted.required_equipment ?? []).map((item) => (
                    <Badge key={item} variant="secondary" className="gap-1">
                      <Wrench className="size-3" />
                      {item}
                    </Badge>
                  ))}
                  {interpreted.preferred_floor ? (
                    <Badge variant="secondary">
                      {interpreted.preferred_floor} 楼偏好
                    </Badge>
                  ) : null}
                </div>
              ) : null}

              {(result.assumptions ?? []).length > 0 ? (
                <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                  {(result.assumptions ?? []).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : null}

              <div className="grid gap-3 rounded-lg border bg-background p-3 sm:grid-cols-2 lg:grid-cols-3">
                <div className="grid gap-1.5">
                  <Label htmlFor="ai-date" className="text-xs">
                    日期
                  </Label>
                  <Input
                    id="ai-date"
                    type="date"
                    value={overrideDate}
                    onChange={(event) => setOverrideDate(event.target.value)}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="ai-start" className="text-xs">
                    搜索开始
                  </Label>
                  <Input
                    id="ai-start"
                    type="time"
                    value={overrideStart}
                    onChange={(event) => setOverrideStart(event.target.value)}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="ai-end" className="text-xs">
                    搜索结束
                  </Label>
                  <Input
                    id="ai-end"
                    type="time"
                    value={overrideEnd}
                    onChange={(event) => setOverrideEnd(event.target.value)}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="ai-duration" className="text-xs">
                    时长（分钟）
                  </Label>
                  <Input
                    id="ai-duration"
                    type="number"
                    min={30}
                    max={240}
                    step={30}
                    value={overrideDuration}
                    onChange={(event) =>
                      setOverrideDuration(event.target.value)
                    }
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="ai-party" className="text-xs">
                    人数
                  </Label>
                  <Input
                    id="ai-party"
                    type="number"
                    min={1}
                    value={overrideParty}
                    onChange={(event) => setOverrideParty(event.target.value)}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="ai-floor" className="text-xs">
                    楼层偏好
                  </Label>
                  <Input
                    id="ai-floor"
                    type="number"
                    value={overrideFloor}
                    onChange={(event) => setOverrideFloor(event.target.value)}
                  />
                </div>
                <div className="grid gap-1.5 sm:col-span-2 lg:col-span-3">
                  <Label htmlFor="ai-equipment" className="text-xs">
                    必需设备（用顿号或逗号分隔）
                  </Label>
                  <Input
                    id="ai-equipment"
                    placeholder="投影仪、白板、视频会议"
                    value={overrideEquipment}
                    onChange={(event) =>
                      setOverrideEquipment(event.target.value)
                    }
                  />
                </div>
                <div className="sm:col-span-2 lg:col-span-3">
                  <LoadingButton
                    variant="secondary"
                    loading={recommendMutation.isPending}
                    disabled={
                      !overrideDate || !overrideDuration || !overrideParty
                    }
                    onClick={() => submit(true)}
                  >
                    <RefreshCw className="size-4" />
                    按修正条件重新推荐
                  </LoadingButton>
                </div>
              </div>

              {(result.suggestions ?? []).length > 0 ? (
                <div className="grid gap-3">
                  <p className="text-xs text-muted-foreground">
                    查询时可用，最终以提交结果为准。每个资源最多展示两个时段。
                  </p>
                  {(result.suggestions ?? []).map((suggestion) => {
                    const active =
                      selected?.resource_id === suggestion.resource_id &&
                      selected?.start_at === suggestion.start_at
                    return (
                      <button
                        key={`${suggestion.resource_id}-${suggestion.start_at}`}
                        type="button"
                        className={`rounded-xl border p-3 text-left transition-all ${
                          active
                            ? "border-primary bg-primary/5 ring-1 ring-primary/30"
                            : "bg-background hover:border-primary/40"
                        }`}
                        onClick={() => chooseSuggestion(suggestion)}
                      >
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <p className="font-medium">
                              {suggestion.resource_name}
                            </p>
                            <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                              <MapPin className="size-3" />
                              {suggestion.location}
                            </p>
                          </div>
                          <Badge variant={active ? "default" : "outline"}>
                            {active ? "已选择" : "选择"}
                          </Badge>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                          <span className="flex items-center gap-1">
                            <Clock className="size-3" />
                            {formatRange(
                              suggestion.start_at,
                              suggestion.end_at,
                              suggestion.timezone,
                            )}
                          </span>
                          <span className="flex items-center gap-1">
                            <Users className="size-3" />
                            容量 {suggestion.capacity} 人
                          </span>
                          {(suggestion.equipment ?? []).map((item) => (
                            <span key={item}>· {item}</span>
                          ))}
                        </div>
                        <p className="mt-2 text-xs leading-5 text-muted-foreground">
                          {suggestion.reason}
                        </p>
                      </button>
                    )
                  })}
                </div>
              ) : null}

              {confirmed ? (
                <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm dark:border-emerald-800 dark:bg-emerald-950/40">
                  <p className="font-medium text-emerald-800 dark:text-emerald-300">
                    预约成功
                  </p>
                  <p className="mt-1 text-xs text-emerald-700 dark:text-emerald-400">
                    {confirmed.resourceName} ·{" "}
                    {formatRange(
                      confirmed.startAt,
                      confirmed.endAt,
                      interpreted?.timezone ?? "Asia/Shanghai",
                    )}
                  </p>
                  <p className="mt-1 break-all font-mono text-xs">
                    订单号：{confirmed.id}
                  </p>
                  <Button asChild size="sm" variant="outline" className="mt-3">
                    <Link to="/reservations">查看我的预约</Link>
                  </Button>
                </div>
              ) : null}

              {conflict ? (
                <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                  该时段已被其他人占用。请点击“分析并推荐”重新查询，或选择其他候选时段。
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            关闭
          </Button>
          {selected && !confirmed ? (
            <LoadingButton
              loading={confirmMutation.isPending}
              disabled={!idempotencyKey}
              onClick={() => confirmMutation.mutate(selected)}
            >
              <CheckCircle2 className="size-4" />
              确认预约
            </LoadingButton>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
