import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useState } from "react"

import { OrganizationsService } from "@/client"
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
import useCustomToast from "@/hooks/useCustomToast"
import { useOrg } from "@/hooks/useOrg"
import { handleError } from "@/utils"

export function CreateOrganizationDialog() {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { setCurrentOrgId, refresh } = useOrg()

  const mutation = useMutation({
    mutationFn: async () =>
      (
        await OrganizationsService.createOrganization({
          body: { name: name.trim() },
        })
      ).data,
    onSuccess: async (organization) => {
      showSuccessToast(`组织「${organization.name}」已创建`)
      setOpen(false)
      setName("")
      await queryClient.invalidateQueries({ queryKey: ["organizations"] })
      refresh()
      setCurrentOrgId(organization.id)
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="mr-2 size-4" />
          创建组织
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>创建组织</DialogTitle>
          <DialogDescription>
            组织是资源与预约的隔离边界，创建后你将成为该组织的管理员。
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-2 py-2">
          <Label htmlFor="org-name">组织名称</Label>
          <Input
            id="org-name"
            placeholder="例如：NexaSlot 总部"
            value={name}
            maxLength={120}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <DialogFooter>
          <LoadingButton
            loading={mutation.isPending}
            disabled={name.trim().length === 0}
            onClick={() => mutation.mutate()}
          >
            创建
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
