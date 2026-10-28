import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { DoorOpen, MapPinned, Plus, TicketCheck, Trash2 } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import {
  type MemberPublic,
  OrganizationsService,
  ReservationsService,
  ResourcesService,
  SitesService,
  WaitlistService,
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
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { useOrg } from "@/hooks/useOrg"
import { formatDateTime, formatRange } from "@/lib/datetime"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/admin")({
  component: AdminPage,
  head: () => ({
    meta: [{ title: "管理后台 - NexaSlot" }],
  }),
})

const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

function AdminPage() {
  const { currentOrgId, canManageResources, isAdmin } = useOrg()

  if (!currentOrgId) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-muted-foreground">
          请先创建或加入一个组织。
        </CardContent>
      </Card>
    )
  }
  if (!canManageResources) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-muted-foreground">
          你没有该组织的资源管理权限。
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">管理后台</h1>
        <p className="text-sm text-muted-foreground">
          维护场地、资源与开放时间，并查看组织的预约记录
        </p>
      </div>

      <Tabs defaultValue="resources">
        <TabsList className="flex flex-wrap">
          <TabsTrigger value="resources">资源</TabsTrigger>
          <TabsTrigger value="sites">场地</TabsTrigger>
          <TabsTrigger value="rules">开放时间</TabsTrigger>
          <TabsTrigger value="reservations">预约记录</TabsTrigger>
          <TabsTrigger value="waitlist">候补队列</TabsTrigger>
          {isAdmin ? <TabsTrigger value="members">成员</TabsTrigger> : null}
        </TabsList>

        <TabsContent value="resources" className="mt-4">
          <ResourcesTab orgId={currentOrgId} />
        </TabsContent>
        <TabsContent value="sites" className="mt-4">
          <SitesTab orgId={currentOrgId} />
        </TabsContent>
        <TabsContent value="rules" className="mt-4">
          <RulesTab orgId={currentOrgId} />
        </TabsContent>
        <TabsContent value="reservations" className="mt-4">
          <ReservationsTab orgId={currentOrgId} />
        </TabsContent>
        <TabsContent value="waitlist" className="mt-4">
          <WaitlistTab orgId={currentOrgId} />
        </TabsContent>
        {isAdmin ? (
          <TabsContent value="members" className="mt-4">
            <MembersTab orgId={currentOrgId} />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Sites                                                               */
/* ------------------------------------------------------------------ */

function SitesTab({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [address, setAddress] = useState("")

  const { data, isLoading } = useQuery({
    queryKey: ["sites", orgId, "all"],
    queryFn: async () =>
      (
        await SitesService.readSites({
          path: { org_id: orgId },
          query: { include_inactive: true },
        })
      ).data,
  })

  const createMutation = useMutation({
    mutationFn: async () =>
      (
        await SitesService.createSite({
          path: { org_id: orgId },
          body: {
            name: name.trim(),
            address: address.trim() || null,
            timezone: "Asia/Shanghai",
          },
        })
      ).data,
    onSuccess: async () => {
      showSuccessToast("场地已创建")
      setOpen(false)
      setName("")
      setAddress("")
      await queryClient.invalidateQueries({ queryKey: ["sites"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const toggleMutation = useMutation({
    mutationFn: async (variables: { siteId: string; status: string }) =>
      (
        await SitesService.updateSite({
          path: { org_id: orgId, site_id: variables.siteId },
          body: { status: variables.status },
        })
      ).data,
    onSuccess: async () => {
      showSuccessToast("场地状态已更新")
      await queryClient.invalidateQueries({ queryKey: ["sites"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const sites = data?.data ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          共 {sites.length} 个场地
        </p>
        <Button onClick={() => setOpen(true)}>
          <Plus className="mr-2 size-4" />
          新建场地
        </Button>
      </div>

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : sites.length === 0 ? (
        <EmptyState
          icon={<MapPinned className="size-6" />}
          title="还没有场地"
          hint="先创建场地，再在场地下面发布会议室等资源。"
        />
      ) : (
        <Card className="py-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>地址</TableHead>
                <TableHead>时区</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sites.map((site) => (
                <TableRow key={site.id}>
                  <TableCell className="font-medium">{site.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {site.address || "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {site.timezone}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        site.status === "ACTIVE" ? "default" : "secondary"
                      }
                    >
                      {site.status === "ACTIVE" ? "启用" : "停用"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        toggleMutation.mutate({
                          siteId: site.id,
                          status:
                            site.status === "ACTIVE" ? "INACTIVE" : "ACTIVE",
                        })
                      }
                    >
                      {site.status === "ACTIVE" ? "停用" : "启用"}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>新建场地</DialogTitle>
            <DialogDescription>
              场地是资源的归属位置，例如「总部 A 座」。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 py-2">
            <div className="grid gap-2">
              <Label htmlFor="site-name">场地名称</Label>
              <Input
                id="site-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="例如：总部 A 座"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="site-address">地址（可选）</Label>
              <Input
                id="site-address"
                value={address}
                onChange={(event) => setAddress(event.target.value)}
                placeholder="例如：上海市浦东新区世纪大道 100 号"
              />
            </div>
          </div>
          <DialogFooter>
            <LoadingButton
              loading={createMutation.isPending}
              disabled={name.trim().length === 0}
              onClick={() => createMutation.mutate()}
            >
              创建
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Resources                                                           */
/* ------------------------------------------------------------------ */

function ResourcesTab({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [siteId, setSiteId] = useState("")
  const [name, setName] = useState("")
  const [capacity, setCapacity] = useState("6")
  const [features, setFeatures] = useState("")
  const [description, setDescription] = useState("")

  const sitesQuery = useQuery({
    queryKey: ["sites", orgId, "all"],
    queryFn: async () =>
      (
        await SitesService.readSites({
          path: { org_id: orgId },
          query: { include_inactive: true },
        })
      ).data,
  })

  const resourcesQuery = useQuery({
    queryKey: ["resources-admin", orgId],
    queryFn: async () =>
      (
        await ResourcesService.readResources({
          path: { org_id: orgId },
          query: { page: 1, page_size: 100 },
        })
      ).data,
  })

  const activeSites = useMemo(
    () =>
      (sitesQuery.data?.data ?? []).filter((site) => site.status === "ACTIVE"),
    [sitesQuery.data],
  )

  useEffect(() => {
    if (!siteId && activeSites.length > 0) {
      setSiteId(activeSites[0].id)
    }
  }, [activeSites, siteId])

  const createMutation = useMutation({
    mutationFn: async () =>
      (
        await ResourcesService.createResource({
          path: { org_id: orgId },
          body: {
            site_id: siteId,
            name: name.trim(),
            capacity: Number(capacity) || 1,
            description: description.trim() || null,
            features: features
              .split(/[,，]/)
              .map((item) => item.trim())
              .filter(Boolean),
          },
        })
      ).data,
    onSuccess: async () => {
      showSuccessToast("资源已创建")
      setOpen(false)
      setName("")
      setFeatures("")
      setDescription("")
      await queryClient.invalidateQueries({ queryKey: ["resources"] })
      await queryClient.invalidateQueries({ queryKey: ["resources-admin"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const toggleMutation = useMutation({
    mutationFn: async (variables: { resourceId: string; status: string }) =>
      (
        await ResourcesService.updateResource({
          path: { resource_id: variables.resourceId },
          body: { status: variables.status },
        })
      ).data,
    onSuccess: async () => {
      showSuccessToast("资源状态已更新")
      await queryClient.invalidateQueries({ queryKey: ["resources"] })
      await queryClient.invalidateQueries({ queryKey: ["resources-admin"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const resources = resourcesQuery.data?.data ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          共 {resources.length} 个资源
        </p>
        <Button
          onClick={() => setOpen(true)}
          disabled={activeSites.length === 0}
          title={activeSites.length === 0 ? "请先创建并启用场地" : undefined}
        >
          <Plus className="mr-2 size-4" />
          新建资源
        </Button>
      </div>

      {resourcesQuery.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : resources.length === 0 ? (
        <EmptyState
          icon={<DoorOpen className="size-6" />}
          title="还没有资源"
          hint="创建会议室、工位或设备，并设置开放时间后即可被预约。"
        />
      ) : (
        <Card className="py-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>场地</TableHead>
                <TableHead>容量</TableHead>
                <TableHead>设备</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {resources.map((resource) => (
                <TableRow key={resource.id}>
                  <TableCell className="font-medium">{resource.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {resource.site_name}
                  </TableCell>
                  <TableCell>{resource.capacity} 人</TableCell>
                  <TableCell className="max-w-48 truncate text-muted-foreground">
                    {resource.features.join("、") || "—"}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        resource.status === "ACTIVE" ? "default" : "secondary"
                      }
                    >
                      {resource.status === "ACTIVE" ? "可预约" : "已停用"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        toggleMutation.mutate({
                          resourceId: resource.id,
                          status:
                            resource.status === "ACTIVE"
                              ? "INACTIVE"
                              : "ACTIVE",
                        })
                      }
                    >
                      {resource.status === "ACTIVE" ? "停用" : "启用"}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>新建资源</DialogTitle>
            <DialogDescription>
              资源是独占预约单元，同一时段只会有一笔有效预约。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 py-2">
            <div className="grid gap-2">
              <Label>所属场地</Label>
              <Select value={siteId} onValueChange={setSiteId}>
                <SelectTrigger>
                  <SelectValue placeholder="选择场地" />
                </SelectTrigger>
                <SelectContent>
                  {activeSites.map((site) => (
                    <SelectItem key={site.id} value={site.id}>
                      {site.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="resource-name">资源名称</Label>
              <Input
                id="resource-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="例如：星河会议室"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="resource-capacity">容纳人数</Label>
              <Input
                id="resource-capacity"
                type="number"
                min={1}
                value={capacity}
                onChange={(event) => setCapacity(event.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="resource-features">设备标签（逗号分隔）</Label>
              <Input
                id="resource-features"
                value={features}
                onChange={(event) => setFeatures(event.target.value)}
                placeholder="投影仪, 视频会议, 白板"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="resource-desc">描述（可选）</Label>
              <Input
                id="resource-desc"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="例如：12 人间，带落地窗"
              />
            </div>
          </div>
          <DialogFooter>
            <LoadingButton
              loading={createMutation.isPending}
              disabled={!siteId || name.trim().length === 0}
              onClick={() => createMutation.mutate()}
            >
              创建
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Opening rules                                                       */
/* ------------------------------------------------------------------ */

type RuleRow = { enabled: boolean; start: string; end: string }

function RulesTab({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [resourceId, setResourceId] = useState("")
  const [rows, setRows] = useState<RuleRow[]>(
    Array.from({ length: 7 }, (_, index) => ({
      enabled: index < 5,
      start: "09:00",
      end: "18:00",
    })),
  )

  const resourcesQuery = useQuery({
    queryKey: ["resources-admin", orgId],
    queryFn: async () =>
      (
        await ResourcesService.readResources({
          path: { org_id: orgId },
          query: { page: 1, page_size: 100 },
        })
      ).data,
  })

  const resources = resourcesQuery.data?.data ?? []

  useEffect(() => {
    if (!resourceId && resources.length > 0) {
      setResourceId(resources[0].id)
    }
  }, [resources, resourceId])

  const rulesQuery = useQuery({
    queryKey: ["opening-rules", resourceId],
    queryFn: async () =>
      (
        await ResourcesService.readOpeningRules({
          path: { resource_id: resourceId },
        })
      ).data,
    enabled: Boolean(resourceId),
  })

  useEffect(() => {
    const existing = rulesQuery.data?.data ?? []
    setRows(
      Array.from({ length: 7 }, (_, weekday) => {
        const rule = existing.find((item) => item.weekday === weekday)
        return {
          enabled: Boolean(rule),
          start: rule?.start_time.slice(0, 5) ?? "09:00",
          end: rule?.end_time.slice(0, 5) ?? "18:00",
        }
      }),
    )
  }, [rulesQuery.data])

  const saveMutation = useMutation({
    mutationFn: async () =>
      (
        await ResourcesService.replaceOpeningRules({
          path: { resource_id: resourceId },
          body: {
            rules: rows
              .map((row, weekday) => ({ row, weekday }))
              .filter(({ row }) => row.enabled)
              .map(({ row, weekday }) => ({
                weekday,
                start_time: `${row.start}:00`,
                end_time: `${row.end}:00`,
              })),
          },
        })
      ).data,
    onSuccess: async () => {
      showSuccessToast("开放时间已保存")
      await queryClient.invalidateQueries({ queryKey: ["availability"] })
      await queryClient.invalidateQueries({ queryKey: ["opening-rules"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <Card className="py-5">
      <CardContent className="flex flex-col gap-4 px-5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-muted-foreground">资源</span>
          <Select value={resourceId} onValueChange={setResourceId}>
            <SelectTrigger className="w-64">
              <SelectValue placeholder="选择资源" />
            </SelectTrigger>
            <SelectContent>
              {resources.map((resource) => (
                <SelectItem key={resource.id} value={resource.id}>
                  {resource.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-xs text-muted-foreground">
            时间片固定 30 分钟，保存后立即生效
          </span>
        </div>

        {resources.length === 0 ? (
          <p className="text-sm text-muted-foreground">请先创建资源。</p>
        ) : (
          <div className="flex flex-col divide-y rounded-lg border">
            {rows.map((row, weekday) => (
              <div
                key={weekday}
                className="flex flex-wrap items-center gap-3 px-4 py-2.5"
              >
                <label className="flex w-24 items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={row.enabled}
                    onChange={(event) =>
                      setRows((current) =>
                        current.map((item, index) =>
                          index === weekday
                            ? { ...item, enabled: event.target.checked }
                            : item,
                        ),
                      )
                    }
                  />
                  {WEEKDAYS[weekday]}
                </label>
                <input
                  type="time"
                  step={1800}
                  className="rounded-md border bg-background px-2 py-1 text-sm disabled:opacity-50"
                  value={row.start}
                  disabled={!row.enabled}
                  onChange={(event) =>
                    setRows((current) =>
                      current.map((item, index) =>
                        index === weekday
                          ? { ...item, start: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
                <span className="text-muted-foreground">至</span>
                <input
                  type="time"
                  step={1800}
                  className="rounded-md border bg-background px-2 py-1 text-sm disabled:opacity-50"
                  value={row.end}
                  disabled={!row.enabled}
                  onChange={(event) =>
                    setRows((current) =>
                      current.map((item, index) =>
                        index === weekday
                          ? { ...item, end: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-end">
          <LoadingButton
            loading={saveMutation.isPending}
            disabled={!resourceId}
            onClick={() => saveMutation.mutate()}
          >
            保存开放时间
          </LoadingButton>
        </div>
      </CardContent>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Reservations                                                        */
/* ------------------------------------------------------------------ */

function ReservationsTab({ orgId }: { orgId: string }) {
  const [status, setStatus] = useState("all")

  const { data, isLoading } = useQuery({
    queryKey: ["org-reservations", orgId, status],
    queryFn: async () =>
      (
        await ReservationsService.readOrganizationReservations({
          path: { org_id: orgId },
          query: {
            status: status === "all" ? undefined : status,
            page: 1,
            page_size: 100,
          },
        })
      ).data,
  })

  const reservations = data?.data ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          共 {data?.count ?? 0} 条预约记录
        </p>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            <SelectItem value="CONFIRMED">已确认</SelectItem>
            <SelectItem value="CANCELLED">已取消</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : reservations.length === 0 ? (
        <EmptyState
          icon={<TicketCheck className="size-6" />}
          title="暂无预约记录"
          hint="用户在资源中心提交预约后会显示在这里。"
        />
      ) : (
        <Card className="py-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>资源</TableHead>
                <TableHead>预约人</TableHead>
                <TableHead>时间</TableHead>
                <TableHead>状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {reservations.map((item) => (
                <TableRow key={item.id}>
                  <TableCell>
                    <div className="font-medium">{item.resource_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {item.site_name}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm">{item.user_email}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {formatRange(item.start_at, item.end_at, item.timezone)}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        item.status === "CONFIRMED" ? "default" : "secondary"
                      }
                    >
                      {item.status === "CONFIRMED" ? "已确认" : "已取消"}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Members                                                             */
/* ------------------------------------------------------------------ */

function MembersTab({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState("")
  const [role, setRole] = useState("MEMBER")

  const { data, isLoading } = useQuery({
    queryKey: ["members", orgId],
    queryFn: async () =>
      (await OrganizationsService.readMembers({ path: { org_id: orgId } }))
        .data,
  })

  const addMutation = useMutation({
    mutationFn: async () =>
      (
        await OrganizationsService.addMember({
          path: { org_id: orgId },
          body: { email: email.trim(), role },
        })
      ).data,
    onSuccess: async () => {
      showSuccessToast("成员已添加")
      setOpen(false)
      setEmail("")
      await queryClient.invalidateQueries({ queryKey: ["members"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const roleMutation = useMutation({
    mutationFn: async (variables: { userId: string; role: string }) =>
      (
        await OrganizationsService.updateMemberRole({
          path: { org_id: orgId, user_id: variables.userId },
          body: { role: variables.role },
        })
      ).data,
    onSuccess: async () => {
      showSuccessToast("角色已更新")
      await queryClient.invalidateQueries({ queryKey: ["members"] })
      await queryClient.invalidateQueries({ queryKey: ["organizations"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const removeMutation = useMutation({
    mutationFn: async (userId: string) =>
      OrganizationsService.removeMember({
        path: { org_id: orgId, user_id: userId },
      }),
    onSuccess: async () => {
      showSuccessToast("成员已移除")
      await queryClient.invalidateQueries({ queryKey: ["members"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  const members: MemberPublic[] = data?.data ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          共 {members.length} 位成员
        </p>
        <Button onClick={() => setOpen(true)}>
          <Plus className="mr-2 size-4" />
          添加成员
        </Button>
      </div>

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <Card className="py-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>邮箱</TableHead>
                <TableHead>姓名</TableHead>
                <TableHead>角色</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.map((member) => (
                <TableRow key={member.user_id}>
                  <TableCell className="font-medium">{member.email}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {member.full_name || "—"}
                  </TableCell>
                  <TableCell>
                    <Select
                      value={member.role}
                      onValueChange={(value) =>
                        roleMutation.mutate({
                          userId: member.user_id,
                          role: value,
                        })
                      }
                    >
                      <SelectTrigger className="h-8 w-40">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="MEMBER">成员</SelectItem>
                        <SelectItem value="RESOURCE_MANAGER">
                          资源管理员
                        </SelectItem>
                        <SelectItem value="ORG_ADMIN">组织管理员</SelectItem>
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => removeMutation.mutate(member.user_id)}
                    >
                      <Trash2 className="size-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>添加成员</DialogTitle>
            <DialogDescription>
              对方需要先注册账号，然后输入其邮箱加入组织。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 py-2">
            <div className="grid gap-2">
              <Label htmlFor="member-email">邮箱</Label>
              <Input
                id="member-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="member@example.com"
              />
            </div>
            <div className="grid gap-2">
              <Label>角色</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="MEMBER">成员（可预约）</SelectItem>
                  <SelectItem value="RESOURCE_MANAGER">资源管理员</SelectItem>
                  <SelectItem value="ORG_ADMIN">组织管理员</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <LoadingButton
              loading={addMutation.isPending}
              disabled={email.trim().length === 0}
              onClick={() => addMutation.mutate()}
            >
              添加
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

const WAITLIST_STATUS_LABEL: Record<string, string> = {
  WAITING: "排队中",
  OFFERED: "待确认",
  CONFIRMED: "已确认",
  EXPIRED: "已过期",
  DECLINED: "已拒绝",
  CANCELLED: "已退出",
}

function WaitlistTab({ orgId }: { orgId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["waitlist", "org", orgId],
    queryFn: async () =>
      (
        await WaitlistService.readOrganizationWaitlist({
          query: { org_id: orgId, page: 1, page_size: 100 },
        })
      ).data,
    refetchInterval: 15_000,
  })

  if (isLoading) {
    return <Skeleton className="h-48 w-full" />
  }
  if ((data?.data.length ?? 0) === 0) {
    return (
      <EmptyState
        icon={<TicketCheck className="size-6" />}
        title="暂无候补记录"
        hint="资源时段被占满后，成员可以在资源详情页加入候补。"
      />
    )
  }

  return (
    <Card>
      <CardContent className="px-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>成员</TableHead>
              <TableHead>资源</TableHead>
              <TableHead>候补时段</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>排队</TableHead>
              <TableHead>确认截止</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.data.map((entry) => (
              <TableRow key={entry.id}>
                <TableCell className="text-xs">{entry.user_email}</TableCell>
                <TableCell>{entry.resource_name}</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatRange(entry.start_at, entry.end_at, entry.timezone)}
                </TableCell>
                <TableCell>
                  <Badge
                    variant={
                      entry.status === "OFFERED" ? "default" : "secondary"
                    }
                  >
                    {WAITLIST_STATUS_LABEL[entry.status] ?? entry.status}
                  </Badge>
                </TableCell>
                <TableCell>{entry.queue_position ?? "—"}</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {entry.hold
                    ? formatDateTime(entry.hold.expires_at, entry.timezone)
                    : "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function EmptyState({
  icon,
  title,
  hint,
}: {
  icon: React.ReactNode
  title: string
  hint: string
}) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-14 text-center">
        <div className="grid size-12 place-items-center rounded-full bg-muted text-muted-foreground">
          {icon}
        </div>
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="max-w-md text-sm text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  )
}
