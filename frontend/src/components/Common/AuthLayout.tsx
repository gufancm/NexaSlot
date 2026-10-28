import { PublicShell } from "@/components/Common/PublicShell"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <PublicShell>
      <div className="flex flex-1 items-center justify-center px-4 py-8 sm:px-6 sm:py-12">
        <div className="w-full max-w-sm rounded-2xl border bg-card/85 p-6 shadow-xl shadow-black/5 backdrop-blur-sm sm:p-8">
          {children}
        </div>
      </div>
    </PublicShell>
  )
}
