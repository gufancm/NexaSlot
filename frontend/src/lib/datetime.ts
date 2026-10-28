export function formatDate(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  }).format(new Date(iso))
}

export function formatTime(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso))
}

export function formatDateTime(iso: string, timeZone: string): string {
  return `${formatDate(iso, timeZone)} ${formatTime(iso, timeZone)}`
}

export function formatRange(
  startIso: string,
  endIso: string,
  timeZone: string,
): string {
  return `${formatDate(startIso, timeZone)} ${formatTime(startIso, timeZone)} - ${formatTime(endIso, timeZone)}`
}

export function todayInTimeZone(timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date())
}

export function formatYmd(dateString: string): string {
  const [year, month, day] = dateString.split("-").map(Number)
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "UTC",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  }).format(new Date(Date.UTC(year, month - 1, day, 12)))
}

export function addDays(dateString: string, days: number): string {
  const [year, month, day] = dateString.split("-").map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

export function slotLabel(iso: string, timeZone: string): string {
  return formatTime(iso, timeZone)
}
