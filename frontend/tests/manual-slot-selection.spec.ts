import { expect, test } from "@playwright/test"

import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

const API = process.env.VITE_API_URL ?? "http://localhost:8001"
const API_V1 = `${API}/api/v1`

async function setupResource(
  request: import("@playwright/test").APIRequestContext,
) {
  const login = await request.post(`${API_V1}/login/access-token`, {
    form: {
      username: firstSuperuser,
      password: firstSuperuserPassword,
    },
  })
  expect(login.ok()).toBeTruthy()
  const token = (await login.json()).access_token as string
  const headers = { Authorization: `Bearer ${token}` }
  const suffix = Math.random().toString(36).slice(2, 8)

  const organization = await request.post(`${API_V1}/organizations`, {
    headers,
    data: { name: `E2E 手动预约 ${suffix}` },
  })
  expect(organization.ok()).toBeTruthy()
  const orgId = (await organization.json()).id as string

  const site = await request.post(`${API_V1}/organizations/${orgId}/sites`, {
    headers,
    data: {
      name: "E2E B座",
      address: "上海市测试路 2 号",
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
        name: "E2E 选择测试会议室",
        capacity: 8,
        features: ["投影"],
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
  return { orgId, resourceId }
}

test("手动预约：再次点击已选时段可取消选择", async ({ page, request }) => {
  const ctx = await setupResource(request)
  await page.goto("/resources")
  await page.evaluate((orgId) => {
    localStorage.setItem("nexaslot_org_id", orgId)
    localStorage.setItem("vite-ui-theme", "light")
  }, ctx.orgId)
  await page.goto(`/resources/${ctx.resourceId}`)

  await expect(page.getByText("选择预约时段")).toBeVisible({ timeout: 15_000 })
  const availableSlots = page.getByRole("button").filter({ hasText: "可预约" })
  await expect(availableSlots.first()).toBeVisible({ timeout: 15_000 })

  await availableSlots.nth(0).click()
  await availableSlots.nth(1).click()
  await expect(page.getByText("请选择连续时段")).toHaveCount(0)

  await availableSlots.nth(0).click()
  await expect(page.getByText("请选择连续时段")).toBeVisible()
  await expect(
    page.getByRole("button", { name: /提交预约|加入候补/ }),
  ).toBeDisabled()
})
