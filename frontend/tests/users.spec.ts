import { expect, test } from "@playwright/test"
import { createUser } from "./utils/privateApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser } from "./utils/user"

test("Platform users page is accessible for superuser", async ({ page }) => {
  await page.goto("/users")
  await expect(page.getByRole("heading", { name: "平台用户" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Add User" })).toBeVisible()
})

test("Superuser can open the Add User dialog", async ({ page }) => {
  await page.goto("/users")
  await page.getByRole("button", { name: "Add User" }).click()
  await expect(page.getByRole("dialog")).toBeVisible()
  await expect(page.getByPlaceholder("Email")).toBeVisible()
})

test.describe("Platform users access control", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("Non-superuser cannot access the platform users page", async ({
    page,
  }) => {
    const email = randomEmail()
    const password = randomPassword()

    await createUser({ email, password })
    await logInUser(page, email, password)

    await page.goto("/users")

    await expect(
      page.getByRole("heading", { name: "平台用户" }),
    ).not.toBeVisible()
    await expect(page).not.toHaveURL(/\/users/)
  })
})
