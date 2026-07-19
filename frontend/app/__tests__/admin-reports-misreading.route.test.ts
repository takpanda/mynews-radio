/**
 * @jest-environment node
 *
 * Route Handler: GET /api/admin/reports/misreading
 *
 * 認証境界の統合テスト。handleAdminReportRequest（＝ GET ハンドラと同じ経路）を
 * 直接呼び、各認証ケースで fetch が呼ばれる／呼ばれないを検証する。
 *
 * route-utils.ts の個別関数テストも併記（構造カバレッジ用）。
 * ルート経路の挙動確認が目的のため、存在確認は最小限。
 */

import {
  authCheck,
  buildUpstreamUrl,
  buildHeaders,
  proxyToUpstream,
  handleAdminReportRequest,
  HandlerConfig,
} from "../api/admin/reports/misreading/route-utils"

// ---------------------------------------------------------------------------
// 統合テスト — handleAdminReportRequest (GET ハンドラと同じコード経路)
// ---------------------------------------------------------------------------

function makeReq(url: string, authHeader?: string) {
  const headers = new Map<string, string>()
  if (authHeader) headers.set("authorization", authHeader)
  return {
    url,
    headers: { get: (k: string) => headers.get(k.toLowerCase()) ?? null },
  }
}

const VALID_CONFIG: HandlerConfig = {
  apiBase: "http://api:8010",
  adminKey: "secret-123",
  nextjsPrefix: "/api/admin/reports/misreading",
  backendPath: "/admin/reports/misreading",
}

const ORIGINAL_ENV = { ...process.env }

beforeEach(() => {
  global.fetch = jest.fn()
})

afterEach(() => {
  process.env = { ...ORIGINAL_ENV }
})

describe("統合: handleAdminReportRequest", () => {
  it("正しい Bearer → 上流へ1回転送（URL・Authorization一致）", async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200,
      text: () => Promise.resolve('[{"id":1}]'),
    })

    const resp = await handleAdminReportRequest(
      makeReq("http://localhost:3000/api/admin/reports/misreading", "Bearer secret-123"),
      VALID_CONFIG,
    )

    expect(resp.status).toBe(200)
    expect(await resp.json()).toEqual([{ id: 1 }])
    expect(global.fetch).toHaveBeenCalledTimes(1)
    expect(global.fetch).toHaveBeenCalledWith(
      "http://api:8010/admin/reports/misreading",
      {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer secret-123",
        },
      },
    )
  })

  it("認証ヘッダなし → 401、fetch 未呼出し", async () => {
    const resp = await handleAdminReportRequest(
      makeReq("http://localhost:3000/api/admin/reports/misreading"),
      VALID_CONFIG,
    )

    expect(resp.status).toBe(401)
    const body = await resp.json()
    expect(body.detail.toLowerCase()).toContain("admin key")
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it("誤った Bearer → 401、fetch 未呼出し", async () => {
    const resp = await handleAdminReportRequest(
      makeReq("http://localhost:3000/api/admin/reports/misreading", "Bearer wrong-key"),
      VALID_CONFIG,
    )

    expect(resp.status).toBe(401)
    const body = await resp.json()
    expect(body.detail.toLowerCase()).toContain("admin key")
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it("API_KEY 未設定 → 503、fetch 未呼出し", async () => {
    const resp = await handleAdminReportRequest(
      makeReq("http://localhost:3000/api/admin/reports/misreading", "Bearer secret-123"),
      { ...VALID_CONFIG, adminKey: undefined },
    )

    expect(resp.status).toBe(503)
    const body = await resp.json()
    expect(body.detail.toLowerCase()).toContain("api_key")
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it("クエリ付きURL → 上流URLにクエリが転送される", async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200,
      text: () => Promise.resolve("[]"),
    })

    await handleAdminReportRequest(
      makeReq(
        "http://localhost:3000/api/admin/reports/misreading?limit=10",
        "Bearer secret-123",
      ),
      VALID_CONFIG,
    )

    expect(global.fetch).toHaveBeenCalledWith(
      "http://api:8010/admin/reports/misreading?limit=10",
      expect.anything(),
    )
  })

  it("上流がエラー → 504 を返す", async () => {
    ;(global.fetch as jest.Mock).mockRejectedValueOnce(new Error("timeout"))

    const resp = await handleAdminReportRequest(
      makeReq("http://localhost:3000/api/admin/reports/misreading", "Bearer secret-123"),
      VALID_CONFIG,
    )

    expect(resp.status).toBe(504)
    const body = await resp.json()
    expect(body.error).toBe("upstream error")
  })
})

// ---------------------------------------------------------------------------
// 個別関数テスト（構造カバレッジ）
// ---------------------------------------------------------------------------

describe("authCheck（個別）", () => {
  it("正しい Bearer → null", () => {
    const req = { headers: { get: () => "Bearer secret-123" } }
    expect(authCheck(req as any, "secret-123")).toBeNull()
  })
  it("ヘッダなし → 401", async () => {
    const req = { headers: { get: () => null } }
    const r = authCheck(req as any, "secret-123")!
    expect(r.status).toBe(401)
  })
  it("誤キー → 401", async () => {
    const req = { headers: { get: () => "Bearer wrong" } }
    const r = authCheck(req as any, "secret-123")!
    expect(r.status).toBe(401)
  })
  it("キー未設定 → 503", async () => {
    const req = { headers: { get: () => "Bearer anything" } }
    const r = authCheck(req as any, undefined)!
    expect(r.status).toBe(503)
  })
})

describe("buildUpstreamUrl（個別）", () => {
  const BASE = "http://api:8010"
  const NP = "/api/admin/reports/misreading"
  const BP = "/admin/reports/misreading"
  it("ベースパス", () => {
    expect(buildUpstreamUrl("http://h/api/admin/reports/misreading", BASE, NP, BP))
      .toBe("http://api:8010/admin/reports/misreading")
  })
  it("クエリ付き", () => {
    expect(buildUpstreamUrl("http://h/api/admin/reports/misreading?l=1", BASE, NP, BP))
      .toBe("http://api:8010/admin/reports/misreading?l=1")
  })
  it("サブパス付き", () => {
    expect(buildUpstreamUrl("http://h/api/admin/reports/misreading/123", BASE, NP, BP))
      .toBe("http://api:8010/admin/reports/misreading/123")
  })
})

describe("proxyToUpstream（個別）", () => {
  it("200 → 転送", async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200, text: () => Promise.resolve("[]"),
    })
    const r = await proxyToUpstream("http://u", {})
    expect(r.status).toBe(200)
  })
  it("fetch失敗 → 504", async () => {
    ;(global.fetch as jest.Mock).mockRejectedValueOnce(new Error("x"))
    const r = await proxyToUpstream("http://u", {})
    expect(r.status).toBe(504)
  })
})
