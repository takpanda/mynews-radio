export function unauthorized(detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status: 401,
    headers: { "Content-Type": "application/json" },
  })
}

export function authCheck(
  request: { headers: { get: (k: string) => string | null } },
  adminKey: string | undefined,
): Response | null {
  if (!adminKey) {
    return new Response(
      JSON.stringify({ detail: "Admin API requires API_KEY to be configured" }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    )
  }
  const auth = request.headers.get("authorization") || ""
  if (!auth.startsWith("Bearer ")) {
    return unauthorized("Invalid or missing admin key")
  }
  const token = auth.slice(7)
  if (token !== adminKey) {
    return unauthorized("Invalid or missing admin key")
  }
  return null
}

export function buildUpstreamUrl(
  requestUrl: string,
  apiBase: string,
  nextjsPrefix: string,
  backendPath: string,
): string {
  const { pathname, searchParams } = new URL(requestUrl)
  const suffix = pathname.startsWith(nextjsPrefix)
    ? pathname.slice(nextjsPrefix.length)
    : pathname
  let url = `${apiBase}${backendPath}${suffix}`
  if (searchParams.toString()) {
    url += `?${searchParams.toString()}`
  }
  return url
}

export function buildHeaders(adminKey: string | undefined): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  }
  if (adminKey) {
    headers["Authorization"] = `Bearer ${adminKey}`
  }
  return headers
}

export async function proxyToUpstream(
  url: string,
  headers: Record<string, string>,
) {
  try {
    const upstream = await fetch(url, { method: "GET", headers })
    const data = await upstream.text()
    return new Response(data, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    })
  } catch (err) {
    return new Response(JSON.stringify({ error: "upstream error" }), {
      status: 504,
      headers: { "Content-Type": "application/json" },
    })
  }
}

export interface HandlerConfig {
  apiBase: string
  adminKey: string | undefined
  nextjsPrefix: string
  backendPath: string
}

export async function handleAdminReportRequest(
  request: { url: string; headers: { get: (k: string) => string | null } },
  config: HandlerConfig,
): Promise<Response> {
  const authError = authCheck(request, config.adminKey)
  if (authError) return authError

  const upstreamUrl = buildUpstreamUrl(
    request.url,
    config.apiBase,
    config.nextjsPrefix,
    config.backendPath,
  )
  const upstreamHeaders = buildHeaders(config.adminKey)
  return proxyToUpstream(upstreamUrl, upstreamHeaders)
}
