import { NextRequest } from "next/server"
import { handleAdminReportRequest } from "../route-utils"

const CONFIG = {
  apiBase: process.env.API_BASE ?? "http://api:8010",
  adminKey: process.env.API_KEY,
  nextjsPrefix: "/api/admin/reports/misreading",
  backendPath: "/admin/reports/misreading",
}

export async function GET(request: NextRequest) {
  return handleAdminReportRequest(request, CONFIG, "GET")
}

export async function POST(request: NextRequest) {
  const body = await request.text()
  return handleAdminReportRequest(request, CONFIG, "POST", body)
}
