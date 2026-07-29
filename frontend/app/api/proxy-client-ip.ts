import { NextRequest } from "next/server"

/**
 * The Next.js server is the trusted relay for this header. API_KEY is read
 * only on the server and proves to the backend that the value came from this
 * relay rather than from a browser request sent directly to the API.
 */
export function addTrustedClientIp(headers: Record<string, string>, request: NextRequest) {
  const forwardedFor = request.headers.get("x-forwarded-for")
  const clientIp = forwardedFor?.split(",", 1)[0]?.trim() || request.headers.get("x-real-ip")?.trim()
  const proxySecret = process.env.API_KEY
  if (clientIp && proxySecret) {
    headers["X-Proxy-Client-IP"] = clientIp
    headers["X-Proxy-Auth"] = proxySecret
  }
}
