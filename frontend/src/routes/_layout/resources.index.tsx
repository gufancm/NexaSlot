import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Building2, Search } from "lucide-react"
import { useState } from "react"

import { ResourcesService, SitesService } from "@/client"
import { SmartBookingDialog } from "@/components/ai/SmartBookingDialog"
import { CreateOrganizationDialog } from "@/components/Organizations/CreateOrganizationDialog"
import { ResourceCard } from "@/components/Resources/ResourceCard"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useOrg } from "@/hooks/useOrg"

export const Route = createFileRoute("/_layout/resources/")({
  component: ResourceCenter,
  head: () => ({
    meta: [{ title: "资源中心 - NexaSlot" }],
  }),
})

const PAGE_SIZE = 9

function ResourceCenter() {
  const {
    currentOrg,
    currentOrgId,
    organizations,
    isLoading,
    canManageResources,
  } = useOrg()
  const [search, setSearch] = useState("")
  const [query, setQuery] = useState("")
  const [siteId, setSiteId] = useState<string>("all")
  const [page, setPage] = useState(1)

  const sitesQuery = useQuery({
    queryKey: ["sites", currentOrgId],
    queryFn: async () =>
      (await SitesService.readSites({ path: { org_id: currentOrgId! } })).data,
    enabled: Boolean(currentOrgId),
  })

  const resourcesQuery = useQuery({
    queryKey: ["resources", currentOrgId, query, siteId, page],
    queryFn: async () =>
      (
        await ResourcesService.readResources({
          path: { org_id: currentOrgId! },
          query: {
            q: query || undefined,
            site_id: siteId === "all" ? undefined : siteId,
            page,
            page_size: PAGE_SIZE,
          },
        })
      ).data,
    enabled: Boolean(currentOrgId),
  })

  if (isLoading) {
    return <Skeleton className="h-64 w-full" />
  }

  if (organizations.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
          <div className="grid size-12 place-items-center rounded-full bg-muted">
            <Building2 className="size-6 text-muted-foreground" />
          </div>
          <h2 className="text-lg font-semibold">还没有组织</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            先创建一个组织，再在管理后台添加场地、会议室与开放时间，之后就可以开始预约了。
          </p>
          <CreateOrganizationDialog />
        </CardContent>
      </Card>
    )
  }

  const resources = resourcesQuery.data?.data ?? []
  const total = resourcesQuery.data?.count ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight">资源中心</h1>
        <p className="text-sm text-muted-foreground">
          {currentOrg?.name} · 选择资源查看开放时间并预约
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <form
          className="relative flex-1"
          onSubmit={(event) => {
            event.preventDefault()
            setPage(1)
            setQuery(search.trim())
          }}
        >
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
            placeholder="搜索资源名称，例如：星河会议室"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </form>
        <Select
          value={siteId}
          onValueChange={(value) => {
            setSiteId(value)
            setPage(1)
          }}
        >
          <SelectTrigger className="w-full sm:w-48">
            <SelectValue placeholder="全部场地" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部场地</SelectItem>
            {(sitesQuery.data?.data ?? []).map((site) => (
              <SelectItem key={site.id} value={site.id}>
                {site.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <SmartBookingDialog />
      </div>

      {resourcesQuery.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-44 w-full" />
          ))}
        </div>
      ) : resources.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <h2 className="text-lg font-semibold">没有找到可预约资源</h2>
            <p className="text-sm text-muted-foreground">
              调整筛选条件，或让管理员先在管理后台发布资源。
            </p>
            {canManageResources ? (
              <Button asChild variant="outline">
                <Link to="/admin">去管理后台</Link>
              </Button>
            ) : null}
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {resources.map((resource) => (
            <ResourceCard key={resource.id} resource={resource} />
          ))}
        </div>
      )}

      {total > PAGE_SIZE ? (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            共 {total} 个资源 · 第 {page} / {pageCount} 页
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
            >
              上一页
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= pageCount}
              onClick={() => setPage((value) => Math.min(pageCount, value + 1))}
            >
              下一页
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
