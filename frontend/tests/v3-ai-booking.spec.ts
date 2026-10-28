import { expect, test } from "@playwright/test"

import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

const API = process.env.VITE_API_URL ?? "http://localhost:8001"
const API_V1 = `${API}/api/v1`

async function login(request: import("@playwright/test").APIRequestContext) {
  const response = await request.post(`${API_V1}/login/access-token`, {
    form: {
      username: firstSuperuser,
      password: firstSuperuserPassword,
    },
  })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).access_token as string
}

async function setupOrganization(
  request: import("@playwright/test").APIRequestContext,
) {
  const token = await login(request)
  const headers = { Authorization: `Bearer ${token}` }
  const suffix = Math.random().toString(36).slice(2, 8)
  const organization = await request.post(`${API_V1}/organizations`, {
    headers,
    data: { name: `E2E 智能预约 ${suffix}` },
  })
  expect(organization.ok()).toBeTruthy()
  const orgId = (await organization.json()).id as string

  const site = await request.post(`${API_V1}/organizations/${orgId}/sites`, {
    headers,
    data: {
      name: "E2E A座",
      address: "上海市测试路 1 号",
      timezone: "Asia/Shanghai",
    },
  })
  expect(site.ok()).toBeTruthy()
  const siteId = (await site.json()).id as string

  const resource = await request.post(
    `${API_V1}/organizations/${orgId}/resources`,
    {
      headers,
      data: {
        site_id: siteId,
        name: "E2E 星河会议室",
        capacity: 10,
        features: ["投影", "白板"],
      },
    },
  )
  expect(resource.ok()).toBeTruthy()
  const resourceId = (await resource.json()).id as string

  const rules = await request.post(
    `${API_V1}/resources/${resourceId}/opening-rules`,
    {
      headers,
      data: {
        rules: Array.from({ length: 7 }, (_, weekday) => ({
          weekday,
          start_time: "09:00:00",
          end_time: "21:00:00",
        })),
      },
    },
  )
  expect(rules.ok()).toBeTruthy()

  return { token, headers, orgId }
}

async function openDialog(
  page: import("@playwright/test").Page,
  orgId: string,
) {
  await page.goto("/resources")
  await page.evaluate((id) => {
    localStorage.setItem("nexaslot_org_id", id)
    localStorage.setItem("vite-ui-theme", "light")
  }, orgId)
  await page.reload()
  await page.getByRole("button", { name: "智能预约", exact: true }).click()
}

test("智能预约：推荐 → 确认 → 真实订单", async ({ page, request }) => {
  const ctx = await setupOrganization(request)
  await openDialog(page, ctx.orgId)
  await page
    .getByLabel("预约需求")
    .fill("后天下午，8个人，带投影仪，开两个小时")
  await page.getByRole("button", { name: "分析并推荐" }).click()
  await expect(page.getByText(/找到 \d+ 个可用方案/)).toBeVisible({
    timeout: 20_000,
  })
  await expect(
    page.getByText("每个资源最多展示两个时段", { exact: false }),
  ).toBeVisible()
  await page.screenshot({
    path: "../docs/v3-lite/screenshots/smart-booking-top.png",
  })
  const dialog = page.getByRole("dialog")
  await dialog.evaluate((element) => {
    element.scrollTop = element.scrollHeight
  })
  await page.waitForTimeout(200)
  await page.screenshot({
    path: "../docs/v3-lite/screenshots/smart-booking.png",
    fullPage: true,
  })

  await page.getByRole("button", { name: "确认预约" }).click()
  await expect(page.getByText(/订单号：/)).toBeVisible({ timeout: 15_000 })
  const orderLine = await page.getByText(/订单号：/).textContent()
  const reservationId = orderLine?.split("：")[1]?.trim()
  expect(reservationId).toBeTruthy()
  await page.screenshot({
    path: "../docs/v3-lite/screenshots/smart-booking-confirmed.png",
  })

  const cancelled = await request.post(
    `${API_V1}/reservations/${reservationId}/cancel`,
    { headers: ctx.headers },
  )
  expect(cancelled.ok()).toBeTruthy()
})

test("智能预约：缺少条件时提示补充", async ({ page, request }) => {
  const ctx = await setupOrganization(request)
  await openDialog(page, ctx.orgId)
  await page.getByLabel("预约需求").fill("帮我找会议室")
  await page.getByRole("button", { name: "分析并推荐" }).click()
  await expect(
    page.getByText("还需要补充：日期、人数、时长", { exact: false }),
  ).toBeVisible()
})

test("智能预约：无结果时保留手动预约入口", async ({ page, request }) => {
  const ctx = await setupOrganization(request)
  await openDialog(page, ctx.orgId)
  await page
    .getByLabel("预约需求")
    .fill("后天下午，99个人，带投影仪，开两个小时")
  await page.getByRole("button", { name: "分析并推荐" }).click()
  await expect(
    page.getByText("没有找到同时满足人数、设备且在该时段空闲的资源", {
      exact: false,
    }),
  ).toBeVisible({ timeout: 20_000 })
  await page.getByRole("button", { name: "关闭" }).click()
  await expect(page.getByRole("heading", { name: "资源中心" })).toBeVisible()
})

test("智能预约：AI 不可用时降级", async ({ page, request }) => {
  const ctx = await setupOrganization(request)
  await page.route("**/api/v1/ai/recommend", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "unavailable",
        message:
          "智能助手暂时不可用，请使用手动预约入口，原有预约功能不受影响。",
        interpreted: {},
        missing_fields: [],
        assumptions: [],
        suggestions: [],
      }),
    })
  })
  await openDialog(page, ctx.orgId)
  await page.getByLabel("预约需求").fill("明天下午8个人开两小时")
  await page.getByRole("button", { name: "分析并推荐" }).click()
  await expect(
    page.getByText("智能助手暂时不可用", { exact: false }),
  ).toBeVisible()
  await expect(page.getByRole("button", { name: "确认预约" })).toHaveCount(0)
})

test("智能预约：推荐后时段被占用时显示 409", async ({ page, request }) => {
  const ctx = await setupOrganization(request)
  await openDialog(page, ctx.orgId)
  await page
    .getByLabel("预约需求")
    .fill("后天下午，8个人，带投影仪，开两个小时")
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/ai/recommend") &&
      response.status() === 200,
  )
  await page.getByRole("button", { name: "分析并推荐" }).click()
  const body = await (await responsePromise).json()
  expect(body.status).toBe("suggestions")
  const suggestion = body.suggestions[0]

  const occupied = await request.post(`${API_V1}/reservations`, {
    headers: {
      ...ctx.headers,
      "Idempotency-Key": crypto.randomUUID(),
      "Content-Type": "application/json",
    },
    data: {
      resource_id: suggestion.resource_id,
      start_at: suggestion.start_at,
      end_at: suggestion.end_at,
    },
  })
  expect(occupied.ok()).toBeTruthy()
  const reservationId = (await occupied.json()).id as string

  await page.getByRole("button", { name: "确认预约" }).click()
  await expect(
    page.getByText("该时段已被其他人占用", { exact: false }),
  ).toBeVisible({
    timeout: 15_000,
  })

  await request.post(`${API_V1}/reservations/${reservationId}/cancel`, {
    headers: ctx.headers,
  })
})

test("智能预约：AI 不可用时可退回手动预约", async ({ page, request }) => {
  const ctx = await setupOrganization(request)
  await page.route("**/api/v1/ai/recommend", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "unavailable",
        message:
          "智能助手暂时不可用，请使用手动预约入口，原有预约功能不受影响。",
        interpreted: {},
        missing_fields: [],
        assumptions: [],
        suggestions: [],
      }),
    })
  })
  await openDialog(page, ctx.orgId)
  await page.getByLabel("预约需求").fill("明天下午8个人开两小时")
  await page.getByRole("button", { name: "分析并推荐" }).click()
  await expect(
    page.getByText("智能助手暂时不可用", { exact: false }),
  ).toBeVisible()

  await page.getByRole("button", { name: "关闭" }).click()
  await page.getByRole("link", { name: "查看与预约" }).click()
  await expect(page.getByText("选择预约时段")).toBeVisible({
    timeout: 10_000,
  })
})
