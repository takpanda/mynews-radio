import { NextRequest } from "next/server"
import { createHmac } from "node:crypto"

const HMAC_SECRET = process.env.PROXY_CLIENT_IP_HMAC_SECRET

function signingPayload(clientIp: string, method: string, path: string, timestamp: string) {
  return [clientIp, method.toUpperCase(), path, timestamp].join("\n")
}

/** 公開入口が付与したIPだけを、専用HMAC付きで内部APIへ渡す。 */
export function addTrustedClientIp(
  headers: Record<string, string>,
  request: NextRequest,
  upstreamPath: string,
) {
  const clientIp = request.headers.get("x-verified-client-ip")?.trim()
  if (!clientIp || !HMAC_SECRET) return

  const timestamp = String(Math.floor(Date.now() / 1000))
  const signature = createHmac("sha256", HMAC_SECRET)
    .update(signingPayload(clientIp, request.method, upstreamPath, timestamp), "utf8")
    .digest("hex")
  headers["X-Verified-Client-IP"] = clientIp
  headers["X-Verified-Client-IP-Timestamp"] = timestamp
  headers["X-Verified-Client-IP-Signature"] = signature
}
