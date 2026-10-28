import { useQuery } from "@tanstack/react-query"
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react"

import { type OrganizationPublic, OrganizationsService } from "@/client"

const STORAGE_KEY = "nexaslot_org_id"

interface OrgContextValue {
  organizations: OrganizationPublic[]
  currentOrg: OrganizationPublic | null
  currentOrgId: string | null
  isLoading: boolean
  isAdmin: boolean
  canManageResources: boolean
  setCurrentOrgId: (id: string) => void
  refresh: () => void
}

const OrgContext = createContext<OrgContextValue | null>(null)

export function OrgProvider({ children }: { children: React.ReactNode }) {
  const [selectedId, setSelectedId] = useState<string | null>(() =>
    localStorage.getItem(STORAGE_KEY),
  )

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["organizations"],
    queryFn: async () =>
      (await OrganizationsService.readMyOrganizations()).data,
  })

  const organizations = useMemo(() => data?.data ?? [], [data])

  const currentOrg = useMemo(() => {
    const match = organizations.find((org) => org.id === selectedId)
    return match ?? organizations[0] ?? null
  }, [organizations, selectedId])

  useEffect(() => {
    if (currentOrg && currentOrg.id !== selectedId) {
      setSelectedId(currentOrg.id)
      localStorage.setItem(STORAGE_KEY, currentOrg.id)
    }
  }, [currentOrg, selectedId])

  const setCurrentOrgId = useCallback((id: string) => {
    setSelectedId(id)
    localStorage.setItem(STORAGE_KEY, id)
  }, [])

  const value = useMemo<OrgContextValue>(
    () => ({
      organizations,
      currentOrg,
      currentOrgId: currentOrg?.id ?? null,
      isLoading,
      isAdmin: currentOrg?.role === "ORG_ADMIN",
      canManageResources:
        currentOrg?.role === "ORG_ADMIN" ||
        currentOrg?.role === "RESOURCE_MANAGER",
      setCurrentOrgId,
      refresh: () => {
        void refetch()
      },
    }),
    [organizations, currentOrg, isLoading, setCurrentOrgId, refetch],
  )

  return <OrgContext.Provider value={value}>{children}</OrgContext.Provider>
}

export function useOrg(): OrgContextValue {
  const context = useContext(OrgContext)
  if (!context) {
    throw new Error("useOrg must be used inside <OrgProvider>")
  }
  return context
}
