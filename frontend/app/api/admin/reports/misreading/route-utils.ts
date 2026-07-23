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

export function buildHeaders(cookie?: string, adminKey?: string): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  }
  if (cookie) {
    headers["Cookie"] = cookie
  } else if (adminKey) {
    headers["Authorization"] = `Bearer ${adminKey}`
  }
  return headers
}

export async function proxyToUpstream(
  url: string,
  headers: Record<string, string>,
  method: "GET" | "POST" = "GET",
  body?: string,
) {
  try {
    const upstream = await fetch(url, {
      method,
      headers,
      ...(body !== undefined ? { body } : {}),
    })
    const data = await upstream.text()
    return new Response(data, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    })
  } catch {
    return new Response(JSON.stringify({ error: "upstream error" }), {
      status: 504,
      headers: { "Content-Type": "application/json" },
    })
  }
}

export interface HandlerConfig {
  apiBase: string
  adminKey?: string
  nextjsPrefix: string
  backendPath: string
}

export async function handleAdminReportRequest(
  request: { url: string },
  config: HandlerConfig,
  method: "GET" | "POST" = "GET",
  body?: string,
): Promise<Response> {
  const upstreamUrl = buildUpstreamUrl(
    request.url,
    config.apiBase,
    config.nextjsPrefix,
    config.backendPath,
  )
  const cookie = (request as { headers?: { get?: (name: string) => string | null } }).headers?.get?.("cookie") ?? undefined
  const upstreamHeaders = buildHeaders(cookie, config.adminKey)
  return proxyToUpstream(upstreamUrl, upstreamHeaders, method, body)
}
