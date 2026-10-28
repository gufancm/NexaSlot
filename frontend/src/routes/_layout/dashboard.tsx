import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  Building2,
  CalendarCheck2,
  CalendarClock,
  DoorOpen,
  Gauge,
  TicketCheck,
} from "lucide-react"

import { OrganizationsService } from "@/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useOrg } from "@/hooks/useOrg"

export const Route = createFileRoute("/_layout/dashboard")({
  component: DashboardPage,
  head: () => ({
    meta: [{ title: "数据看板 - NexaSlot" }],
  }),
})

function DashboardPage() {
  const { currentOrgId, currentOrg, isAdmin } = useOrg()

  const { data, isLoading } = useQuery({
    queryKey: ["dashboard", currentOrgId],
    queryFn: async () =>
      (
        await OrganizationsService.readDashboard({
          path: { org_id: currentOrgId! },
        })
      ).data,
    enabled: Boolean(currentOrgId) && isAdmin,
  })

  if (!isAdmin) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-muted-foreground">
          只有组织管理员可以查看数据看板。
        </CardContent>
      </Card>
    )
  }

  const stats = [
    {
      title: "即将开始",
      value: data?.reservations_upcoming ?? 0,
      icon: CalendarClock,
      hint: "尚未开始的已确认预约",
    },
    {
      title: "今日预约",
      value: data?.reservations_today ?? 0,
      icon: CalendarCheck2,
      hint: "今天开始的预约数",
    },
    {
      title: "预约总数",
      value: data?.reservations_total ?? 0,
      icon: TicketCheck,
      hint: "组织累计预约",
    },
    {
      title: "资源数",
      value: data?.resources_total ?? 0,
      icon: DoorOpen,
      hint: "全部场地下的资源",
    },
    {
      title: "场地数",
      value: data?.sites_total ?? 0,
      icon: Building2,
      hint: "组织下的场地",
    },
    {
      title: "今日占用率",
      value: `${Math.round((data?.occupied_slot_ratio ?? 0) * 100)}%`,
      icon: Gauge,
      hint: "已预约时间片 / 今日已生成时间片",
    },
  ]

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">数据看板</h1>
        <p className="text-sm text-muted-foreground">
          {currentOrg?.name} · 数据来自实时数据库统计
        </p>
      </div>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-28 w-full" />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {stats.map((stat) => (
            <Card key={stat.title} className="py-5">
              <CardHeader className="flex flex-row items-center justify-between px-5 pb-0">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {stat.title}
                </CardTitle>
                <stat.icon className="size-4 text-primary" />
              </CardHeader>
              <CardContent className="px-5 pt-2">
                <p className="text-3xl font-bold tracking-tight">
                  {stat.value}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {stat.hint}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Card className="py-5">
        <CardContent className="px-5 text-sm text-muted-foreground">
          说明：今日占用率基于当天已经生成的时间片统计；时间片会随着资源开放规则与预约请求自动生成。
        </CardContent>
      </Card>
    </div>
  )
}
