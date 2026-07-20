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
  method: "GET" | "POST" = "GET",
  body?: string,
) {
  try {
    const upstream = await fetch(url, { method, headers, body })
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
  adminKey: string | undefined
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
  const upstreamHeaders = buildHeaders(config.adminKey)
  return proxyToUpstream(upstreamUrl, upstreamHeaders, method, body)
}
