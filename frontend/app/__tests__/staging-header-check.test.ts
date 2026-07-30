/** @jest-environment node */

import { NextRequest } from "next/server"
import { GET } from "../api/staging-header-check/route"

describe("staging header check endpoint", () => {
  const previousAppEnv = process.env.APP_ENV
  const previousHeaderCheck = process.env.STAGING_HEADER_CHECK

  afterEach(() => {
    if (previousAppEnv === undefined) delete process.env.APP_ENV
    else process.env.APP_ENV = previousAppEnv
    if (previousHeaderCheck === undefined) delete process.env.STAGING_HEADER_CHECK
    else process.env.STAGING_HEADER_CHECK = previousHeaderCheck
  })

  it("returns 404 unless the staging-only flag is enabled", async () => {
    process.env.APP_ENV = "production"
    process.env.STAGING_HEADER_CHECK = "1"

    const response = await GET(new NextRequest("http://localhost/api/staging-header-check"))

    expect(response.status).toBe(404)
  })

  it("returns the verified header only in staging and disables caching", async () => {
    process.env.APP_ENV = "staging"
    process.env.STAGING_HEADER_CHECK = "1"

    const response = await GET(new NextRequest("http://localhost/api/staging-header-check", {
      headers: { "X-Verified-Client-IP": "198.51.100.20" },
    }))

    expect(response.status).toBe(200)
    await expect(response.json()).resolves.toEqual({ verifiedClientIp: "198.51.100.20" })
    expect(response.headers.get("Cache-Control")).toBe("no-store")
  })

  it("returns 404 when the staging check is disabled", async () => {
    process.env.APP_ENV = "staging"
    process.env.STAGING_HEADER_CHECK = "0"

    const response = await GET(new NextRequest("http://localhost/api/staging-header-check"))

    expect(response.status).toBe(404)
  })
})
