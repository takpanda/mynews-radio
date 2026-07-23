import { NextRequest } from "next/server"
import { handleAdminReportRequest } from "../route-utils"
import { requireAdminSession } from "../../../auth"

const CONFIG = {
  apiBase: process.env.API_BASE ?? "http://api:8010",
  adminKey: undefined,
  nextjsPrefix: "/api/admin/reports/misreading",
  backendPath: "/admin/reports/misreading",
}

export async function GET(request: NextRequest) {
  const unauthorized = await requireAdminSession(request)
  if (unauthorized) return unauthorized
  return handleAdminReportRequest(request, CONFIG, "GET")
}

export async function POST(request: NextRequest) {
  const unauthorized = await requireAdminSession(request)
  if (unauthorized) return unauthorized
  const body = await request.text()
  return handleAdminReportRequest(request, CONFIG, "POST", body)
}
