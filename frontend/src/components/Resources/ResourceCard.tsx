import { Link } from "@tanstack/react-router"
import { ArrowRight, MapPin, Users } from "lucide-react"

import type { ResourcePublic } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader } from "@/components/ui/card"

export function ResourceCard({ resource }: { resource: ResourcePublic }) {
  const active = resource.status === "ACTIVE"
  return (
    <Link
      to="/resources/$resourceId"
      params={{ resourceId: resource.id }}
      className="group block h-full"
    >
      <Card className="h-full gap-4 py-5 transition group-hover:-translate-y-0.5 group-hover:border-primary/40 group-hover:shadow-md">
        <CardHeader className="gap-1 px-5">
          <div className="flex items-start justify-between gap-3">
            <h3 className="text-base font-semibold leading-tight">
              {resource.name}
            </h3>
            <Badge variant={active ? "default" : "secondary"}>
              {active ? "可预约" : "已停用"}
            </Badge>
          </div>
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            <MapPin className="size-3.5" />
            {resource.site_name}
          </p>
        </CardHeader>
        <CardContent className="flex flex-1 flex-col justify-between gap-3 px-5">
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Users className="size-4" />
            可容纳 {resource.capacity} 人
          </p>
          <div className="flex flex-wrap gap-1.5">
            {resource.features.slice(0, 4).map((feature) => (
              <span
                key={feature}
                className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground"
              >
                {feature}
              </span>
            ))}
          </div>
          <span className="mt-1 inline-flex items-center gap-1 text-sm font-medium text-primary">
            查看与预约
            <ArrowRight className="size-3.5 transition group-hover:translate-x-0.5" />
          </span>
        </CardContent>
      </Card>
    </Link>
  )
}
