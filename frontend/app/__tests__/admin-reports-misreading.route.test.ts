/**
 * @jest-environment node
 *
 * Route Handler: /api/admin/reports/misreading
 *
 * handleAdminReportRequest を直接呼び、GET/POST のプロキシ動作を検証する。
 * 辞書 Route Handler と同様にクライアント側の認証は不要。
 */

import {
  buildUpstreamUrl,
  buildHeaders,
  proxyToUpstream,
  handleAdminReportRequest,
  HandlerConfig,
} from "../api/admin/reports/misreading/route-utils"

// ---------------------------------------------------------------------------
// 統合テスト — handleAdminReportRequest
// ---------------------------------------------------------------------------

function makeReq(url: string) {
  return { url }
}

function makeReqWithBody(url: string): { url: string } {
  return { url }
}

const VALID_CONFIG: HandlerConfig = {
  apiBase: "http://api:8010",
  adminKey: "secret-123",
  nextjsPrefix: "/api/admin/reports/misreading",
  backendPath: "/admin/reports/misreading",
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe("統合: handleAdminReportRequest (GET)", () => {
  it("GET → 上流へ1回転送（URL・Authorization一致）", async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200,
      text: () => Promise.resolve('[{"id":1}]'),
    })

    const resp = await handleAdminReportRequest(
      makeReq("http://localhost:3000/api/admin/reports/misreading"),
      VALID_CONFIG,
      "GET",
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

  it("クエリ付きURL → 上流URLにクエリが転送される", async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200,
      text: () => Promise.resolve("[]"),
    })

    await handleAdminReportRequest(
      makeReq("http://localhost:3000/api/admin/reports/misreading?limit=10"),
      VALID_CONFIG,
      "GET",
    )

    expect(global.fetch).toHaveBeenCalledWith(
      "http://api:8010/admin/reports/misreading?limit=10",
      expect.anything(),
    )
  })

  it("サブパス付き → 上流URLにサブパスが転送される", async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200,
      text: () => Promise.resolve("{}"),
    })

    await handleAdminReportRequest(
      makeReq("http://localhost:3000/api/admin/reports/misreading/5/approve"),
      VALID_CONFIG,
      "POST",
      "{}",
    )

    expect(global.fetch).toHaveBeenCalledWith(
      "http://api:8010/admin/reports/misreading/5/approve",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-123",
        }),
      }),
    )
  })
})

describe("統合: handleAdminReportRequest (POST)", () => {
  it("POST → 上流へ転送（method・body・Authorization一致）", async () => {
    const approveBody = JSON.stringify({})
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200,
      text: () =>
        Promise.resolve(
          JSON.stringify({
            status: "approved",
            report_id: 5,
            dictionary_entry_id: 10,
          }),
        ),
    })

    const resp = await handleAdminReportRequest(
      makeReqWithBody("http://localhost:3000/api/admin/reports/misreading/5/approve"),
      VALID_CONFIG,
      "POST",
      approveBody,
    )

    expect(resp.status).toBe(200)
    const body = await resp.json()
    expect(body.status).toBe("approved")
    expect(body.dictionary_entry_id).toBe(10)
    expect(global.fetch).toHaveBeenCalledTimes(1)
    expect(global.fetch).toHaveBeenCalledWith(
      "http://api:8010/admin/reports/misreading/5/approve",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer secret-123",
        },
        body: approveBody,
      },
    )
  })

  it("上流がエラー → 504 を返す", async () => {
    ;(global.fetch as jest.Mock).mockRejectedValueOnce(new Error("timeout"))

    const resp = await handleAdminReportRequest(
      makeReq("http://localhost:3000/api/admin/reports/misreading"),
      VALID_CONFIG,
      "POST",
      "{}",
    )

    expect(resp.status).toBe(504)
    const body = await resp.json()
    expect(body.error).toBe("upstream error")
  })

  it("上流が400 → そのまま転送", async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 400,
      text: () => Promise.resolve(JSON.stringify({ detail: "bad request" })),
    })

    const resp = await handleAdminReportRequest(
      makeReq("http://localhost:3000/api/admin/reports/misreading/999/approve"),
      VALID_CONFIG,
      "POST",
      "{}",
    )

    expect(resp.status).toBe(400)
    const body = await resp.json()
    expect(body.detail).toBe("bad request")
  })

  it("API_KEY 未設定でもリクエストを転送する（遷移しない）", async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200,
      text: () =>
        Promise.resolve(
          JSON.stringify({ status: "approved", report_id: 1, dictionary_entry_id: 5 }),
        ),
    })

    const config: HandlerConfig = { ...VALID_CONFIG, adminKey: undefined }
    const resp = await handleAdminReportRequest(
      makeReq("http://localhost:3000/api/admin/reports/misreading/1/approve"),
      config,
      "POST",
      "{}",
    )

    expect(resp.status).toBe(200)
  })
})

// ---------------------------------------------------------------------------
// 個別関数テスト（構造カバレッジ）
// ---------------------------------------------------------------------------

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
  it("POST → body付きで転送", async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200, text: () => Promise.resolve("{}"),
    })
    const r = await proxyToUpstream("http://u", { "Content-Type": "application/json" }, "POST", '{"x":1}')
    expect(r.status).toBe(200)
    expect(global.fetch).toHaveBeenCalledWith(
      "http://u",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: '{"x":1}',
      },
    )
  })
})
