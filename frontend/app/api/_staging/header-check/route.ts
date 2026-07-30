import { NextRequest } from "next/server"

export const dynamic = "force-dynamic"

/**
 * Temporary staging-only observation endpoint for the public-entry contract.
 * It is disabled by default and does not log or persist the observed value.
 */
export async function GET(request: NextRequest) {
  if (process.env.STAGING_HEADER_CHECK !== "1") {
    return new Response(null, { status: 404 })
  }

  return Response.json(
    { verifiedClientIp: request.headers.get("x-verified-client-ip") },
    { headers: { "Cache-Control": "no-store" } },
  )
}
