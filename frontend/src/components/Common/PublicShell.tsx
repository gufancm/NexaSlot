import { Link } from "@tanstack/react-router"
import { FaGithub } from "react-icons/fa"

import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import { Button } from "@/components/ui/button"

interface PublicShellProps {
  children: React.ReactNode
}

export function PublicShell({ children }: PublicShellProps) {
  const currentYear = new Date().getFullYear()

  return (
    <div className="relative flex min-h-svh flex-col overflow-hidden bg-background">
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="absolute left-1/2 top-[-18rem] h-[36rem] w-[56rem] -translate-x-1/2 rounded-full bg-primary/10 blur-3xl" />
        <div className="absolute -left-40 top-1/3 size-96 rounded-full bg-primary/5 blur-3xl" />
        <div className="absolute -right-32 top-1/4 size-80 rounded-full bg-indigo-500/10 blur-3xl" />
        <div className="absolute inset-x-0 bottom-0 h-64 bg-linear-to-t from-muted/50 to-transparent" />
      </div>

      <header className="relative z-20 flex h-20 shrink-0 items-center justify-between gap-3 px-5 sm:px-8 lg:px-12">
        <Link
          to="/"
          className="flex items-center gap-2.5"
          aria-label="NexaSlot 首页"
        >
          <Logo variant="icon" className="size-8" asLink={false} />
          <span className="text-lg font-bold tracking-tight">NexaSlot</span>
        </Link>

        <div className="flex items-center gap-1.5 sm:gap-2">
          <Appearance />
          <Button variant="ghost" asChild className="px-2.5 sm:px-4">
            <Link to="/login">Sign in</Link>
          </Button>
          <Button asChild className="px-3.5 sm:px-4">
            <Link to="/signup">Sign up</Link>
          </Button>
        </div>
      </header>

      <main className="relative z-10 flex flex-1 flex-col">{children}</main>

      <footer className="relative z-10 flex shrink-0 flex-col items-center justify-center gap-2 px-6 py-5 text-center text-xs text-muted-foreground sm:flex-row sm:gap-3 sm:text-sm">
        <a
          href="https://github.com/gufancm/NexaSlot"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="GitHub"
          className="text-muted-foreground transition-colors hover:text-foreground"
        >
          <FaGithub className="size-5" />
        </a>
        <p>NexaSlot - 智能资源预约与调度平台 · {currentYear}</p>
      </footer>
    </div>
  )
}
