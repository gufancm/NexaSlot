export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t py-4 px-6">
      <div className="flex items-center justify-center">
        <p className="text-muted-foreground text-sm">
          NexaSlot - 智能资源预约与调度平台 · {currentYear}
        </p>
      </div>
    </footer>
  )
}
