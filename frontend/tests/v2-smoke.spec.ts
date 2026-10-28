import { expect, test } from "@playwright/test"

test.describe("V2 pages", () => {
  test("waitlist page loads", async ({ page }) => {
    await page.goto("/waitlist")
    await expect(page.getByRole("heading", { name: "我的候补" })).toBeVisible()
  })

  test("notification center loads", async ({ page }) => {
    await page.goto("/notifications")
    await expect(page.getByRole("heading", { name: "通知中心" })).toBeVisible()
  })

  test("resource matching page loads", async ({ page }) => {
    await page.goto("/match")
    await expect(page.getByRole("heading", { name: "智能匹配" })).toBeVisible()
  })
})
