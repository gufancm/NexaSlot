import { Bot, CalendarCheck, Sparkles } from "lucide-react"

import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import { Footer } from "./Footer"

interface AuthLayoutProps {
  children: React.ReactNode
}

const features = [
  {
    icon: CalendarCheck,
    title: "资源预约",
    description: "统一管理场地与设备时段",
  },
  {
    icon: Sparkles,
    title: "智能调度",
    description: "自动匹配需求与可用资源",
  },
  {
    icon: Bot,
    title: "AI 助手",
    description: "用自然语言完成预约",
  },
]

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="grid min-h-svh lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-muted dark:bg-zinc-900 lg:flex">
        <div className="pointer-events-none absolute -left-24 -top-24 size-72 rounded-full bg-primary/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-24 -right-24 size-80 rounded-full bg-indigo-500/10 blur-3xl" />

        <div className="relative z-10 flex w-full flex-col items-center justify-center px-10 py-16 text-center">
          <Logo variant="icon" className="size-14" asLink={false} />

          <h1 className="mt-6 text-4xl font-extrabold tracking-tight">
            NexaSlot
          </h1>
          <p className="mt-3 text-lg font-medium text-foreground/80">
            智能资源预约与调度平台
          </p>
          <p className="mt-1 text-sm tracking-wide text-muted-foreground">
            Intelligent Resource Booking &amp; Scheduling Platform
          </p>

          <div className="mt-10 grid w-full max-w-md gap-3 sm:grid-cols-3">
            {features.map(({ icon: Icon, title, description }) => (
              <div
                key={title}
                className="flex flex-col items-center gap-2 rounded-xl border border-border/60 bg-background/60 px-3 py-4 backdrop-blur-sm"
              >
                <Icon className="size-5 text-primary" />
                <span className="text-sm font-semibold">{title}</span>
                <span className="text-xs leading-snug text-muted-foreground">
                  {description}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-4 p-6 md:p-10">
        <div className="flex items-center justify-between">
          <div className="lg:hidden">
            <Logo variant="full" className="h-8" asLink={false} />
          </div>
          <div className="ml-auto">
            <Appearance />
          </div>
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-xs">{children}</div>
        </div>
        <Footer />
      </div>
    </div>
  )
}
