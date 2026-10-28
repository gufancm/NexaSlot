import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowRight, Search, Sparkles, Users } from "lucide-react"
import { useState } from "react"

import {
  type ResourceMatchCandidate,
  SchedulingService,
  SitesService,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
import useCustomToast from "@/hooks/useCustomToast"
import { useOrg } from "@/hooks/useOrg"
import { addDays, todayInTimeZone } from "@/lib/datetime"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/match")({
  component: MatchPage,
  head: () => ({
    meta: [{ title: "智能匹配 - NexaSlot" }],
  }),
})

function MatchPage() {
  const { currentOrgId, currentOrg } = useOrg()
  const { showErrorToast } = useCustomToast()
  const today = todayInTimeZone("Asia/Shanghai")
  const [partySize, setPartySize] = useState(4)
  const [date, setDate] = useState(addDays(today, 1))
  const [startTime, setStartTime] = useState("10:00")
  const [duration, setDuration] = useState(60)
  const [features, setFeatures] = useState("")
  const [siteId, setSiteId] = useState("any")
  const [useWindow, setUseWindow] = useState(true)

  const sitesQuery = useQuery({
    queryKey: ["sites", currentOrgId],
    queryFn: async () =>
      (await SitesService.readSites({ path: { org_id: currentOrgId! } })).data,
    enabled: Boolean(currentOrgId),
  })

  const matchMutation = useMutation({
    mutationFn: async () => {
      const start = new Date(`${date}T${startTime}:00`)
      const end = new Date(start.getTime() + duration * 60_000)
      return (
        await SchedulingService.matchResourceEndpoint({
          body: {
            org_id: currentOrgId!,
            party_size: partySize,
            start_at: useWindow ? start.toISOString() : null,
            end_at: useWindow ? end.toISOString() : null,
            duration_minutes: useWindow ? duration : null,
            required_features: features
              .split(/[,，、]/)
              .map((item) => item.trim())
              .filter(Boolean),
            preferred_site_id: siteId === "any" ? null : siteId,
            limit: 10,
          },
        })
      ).data
    },
    onError: handleError.bind(showErrorToast),
  })

  if (!currentOrgId) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-muted-foreground">
          请先创建或加入一个组织。
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <Sparkles className="size-6 text-primary" />
          智能匹配
        </h1>
        <p className="text-sm text-muted-foreground">
          先按人数、设备、时间和场地做硬约束过滤，再按容量贴合度与偏好做可解释排序。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">匹配条件</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <div className="grid gap-2">
            <Label htmlFor="party-size">人数</Label>
            <Input
              id="party-size"
              type="number"
              min={1}
              value={partySize}
              onChange={(event) =>
                setPartySize(Number(event.target.value) || 1)
              }
            />
          </div>
          <div className="grid gap-2">
            <Label>偏好场地</Label>
            <Select value={siteId} onValueChange={setSiteId}>
              <SelectTrigger>
                <SelectValue placeholder="不限场地" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="any">不限场地</SelectItem>
                {(sitesQuery.data?.data ?? []).map((site) => (
                  <SelectItem key={site.id} value={site.id}>
                    {site.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="features">必需设备（逗号分隔）</Label>
            <Input
              id="features"
              placeholder="投影, 白板"
              value={features}
              onChange={(event) => setFeatures(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="date">日期</Label>
            <Input
              id="date"
              type="date"
              min={today}
              max={addDays(today, 14)}
              value={date}
              onChange={(event) => setDate(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="start-time">开始时间</Label>
            <Input
              id="start-time"
              type="time"
              step={1800}
              value={startTime}
              onChange={(event) => setStartTime(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label>时长</Label>
            <Select
              value={String(duration)}
              onValueChange={(value) => setDuration(Number(value))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[30, 60, 90, 120, 180, 240].map((minutes) => (
                  <SelectItem key={minutes} value={String(minutes)}>
                    {minutes} 分钟
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <label className="flex items-center gap-2 text-sm md:col-span-2">
            <input
              type="checkbox"
              className="size-4 accent-primary"
              checked={useWindow}
              onChange={(event) => setUseWindow(event.target.checked)}
            />
            只推荐该时段真实空闲的资源
          </label>
          <div className="flex items-end justify-end">
            <LoadingButton
              loading={matchMutation.isPending}
              onClick={() => matchMutation.mutate()}
            >
              <Search className="size-4" />
              开始匹配
            </LoadingButton>
          </div>
        </CardContent>
      </Card>

      {matchMutation.data ? (
        matchMutation.data.data.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center text-sm text-muted-foreground">
              没有满足全部硬约束的资源。可以尝试放宽设备、人数或时间条件。
            </CardContent>
          </Card>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">
              为 {currentOrg?.name} 找到 {matchMutation.data.count} 个候选资源
              {matchMutation.data.window_requested ? "（已校验所选时段）" : ""}
            </p>
            {matchMutation.data.data.map((candidate, index) => (
              <CandidateCard
                key={candidate.resource.id}
                candidate={candidate}
                rank={index + 1}
              />
            ))}
          </div>
        )
      ) : null}
    </div>
  )
}

function CandidateCard({
  candidate,
  rank,
}: {
  candidate: ResourceMatchCandidate
  rank: number
}) {
  const resource = candidate.resource
  return (
    <Card className="py-4">
      <CardContent className="flex flex-wrap items-start justify-between gap-4 px-5">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={rank === 1 ? "default" : "secondary"}>
              #{rank}
            </Badge>
            <span className="text-base font-semibold">{resource.name}</span>
            <Badge variant="outline">匹配度 {candidate.score.toFixed(1)}</Badge>
          </div>
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Users className="size-4" />
            可容纳 {resource.capacity} 人 · {resource.site_name}
          </p>
          <div className="flex flex-wrap gap-1.5 pt-1">
            {candidate.reasons.map((reason) => (
              <span
                key={reason}
                className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground"
              >
                {reason}
              </span>
            ))}
          </div>
          {resource.features.length ? (
            <p className="text-xs text-muted-foreground">
              设备：{resource.features.join("、")}
            </p>
          ) : null}
        </div>
        <Button asChild>
          <Link
            to="/resources/$resourceId"
            params={{ resourceId: resource.id }}
          >
            查看空闲时段
            <ArrowRight className="size-4" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  )
}
