import { createFileRoute, Outlet } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/resources")({
  component: ResourcesLayout,
})

function ResourcesLayout() {
  return <Outlet />
}
