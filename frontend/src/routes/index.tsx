import { createFileRoute, Link, redirect } from "@tanstack/react-router"
import {
  ArrowRight,
  Bot,
  CalendarCheck,
  CheckCircle2,
  Sparkles,
} from "lucide-react"

import { PublicShell } from "@/components/Common/PublicShell"
import { Button } from "@/components/ui/button"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/")({
  component: LandingPage,
  beforeLoad: async () => {
    if (isLoggedIn()) {
      throw redirect({ to: "/resources" })
    }
  },
  head: () => ({
    meta: [{ title: "NexaSlot - 智能资源预约与调度平台" }],
  }),
})

const features = [
  {
    icon: CalendarCheck,
    title: "资源预约",
    description: "会议室、工位与设备统一管理，实时查看可用时段。",
  },
  {
    icon: Sparkles,
    title: "智能调度",
    description: "自动匹配预约需求与可用资源，冲突检测与候补分流。",
  },
  {
    icon: Bot,
    title: "AI 助手",
    description: "用自然语言描述需求，获得推荐方案并一键完成预约。",
  },
]

const highlights = ["实时冲突检测", "30 分钟粒度", "可约未来 14 天"]

function LandingPage() {
  return (
    <PublicShell>
      <section className="mx-auto flex w-full max-w-5xl flex-1 flex-col items-center justify-center px-6 pb-10 pt-4 text-center sm:pb-14">
        <div className="inline-flex items-center gap-2 rounded-full border bg-background/70 px-3.5 py-1.5 text-xs font-medium text-muted-foreground backdrop-blur-sm">
          <Sparkles className="size-3.5 text-primary" />
          NexaSlot · Intelligent Resource Scheduling
        </div>

        <h1 className="mt-6 text-4xl font-extrabold tracking-tight sm:text-5xl lg:text-6xl">
          智能资源预约
          <span className="block bg-linear-to-r from-primary via-teal-500 to-indigo-500 bg-clip-text text-transparent">
            与调度平台
          </span>
        </h1>

        <p className="mt-5 max-w-2xl text-sm leading-7 text-muted-foreground sm:text-base">
          统一管理会议室、工位与设备，实时查看空闲时段；从手动预约到 AI
          自然语言下单，让每一次资源调度都更简单、更高效。
        </p>

        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Button asChild size="lg" className="px-6">
            <Link to="/signup">
              免费开始使用
              <ArrowRight className="size-4" />
            </Link>
          </Button>
          <Button asChild size="lg" variant="outline" className="px-6">
            <Link to="/login">登录已有账号</Link>
          </Button>
        </div>

        <div className="mt-11 grid w-full gap-3 sm:grid-cols-3">
          {features.map(({ icon: Icon, title, description }) => (
            <div
              key={title}
              className="rounded-2xl border bg-card/60 p-5 text-left backdrop-blur-sm transition duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5"
            >
              <div className="grid size-9 place-items-center rounded-lg bg-primary/10 text-primary">
                <Icon className="size-5" />
              </div>
              <h2 className="mt-3 text-sm font-semibold">{title}</h2>
              <p className="mt-1.5 text-xs leading-5 text-muted-foreground">
                {description}
              </p>
            </div>
          ))}
        </div>

        <div className="mt-7 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-muted-foreground">
          {highlights.map((item) => (
            <span key={item} className="inline-flex items-center gap-1.5">
              <CheckCircle2 className="size-3.5 text-primary" />
              {item}
            </span>
          ))}
        </div>
      </section>
    </PublicShell>
  )
}
