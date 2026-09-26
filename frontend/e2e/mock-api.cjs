const http = require('node:http')
const { URL } = require('node:url')

const PORT = 8311
const NOW = '2026-01-01T00:00:00Z'
const validMcIds = new Set(['mc-active', 'mc-inactive'])
let programs
let mcs
let mutations

function sampleProgram() {
  const cast = [{
    key: 'host', name: '朝日アナ', role: 'MC', mc_id: 'mc-active',
    voice_fishs2pro: null, voice_aivispeech: null, voice_voicevox: null,
  }]
  const segmentKinds = ['intro', 'headline', 'news', 'discussion', 'outro']
  return {
    id: 'morning',
    name: '朝のニュース',
    kind: 'radio',
    definition: {
      id: 'morning', name: '朝のニュース', kind: 'radio', cast,
      segments: segmentKinds.map((kind, index) => ({
        id: `segment-${index + 1}`, kind, order: index, min_lines: 0, max_lines: 2,
        speaker_keys: ['host'], label: `パート${index + 1}`,
      })),
      options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' },
    },
    is_active: true, created_at: NOW, updated_at: NOW,
  }
}

function initialMcs() {
  return [
    { id: 'mc-active', name: '青木', role: 'メインMC', voice_fishs2pro: null, voice_aivispeech: null, voice_voicevox: null, is_active: true, created_at: NOW, updated_at: NOW },
    { id: 'mc-inactive', name: '休止中MC', role: 'MC', voice_fishs2pro: null, voice_aivispeech: null, voice_voicevox: null, is_active: false, created_at: NOW, updated_at: NOW },
    // APIが返したものの参照先としては無効な記録を用い、422をUI経由で再現する。
    { id: 'mc-orphan', name: '参照無効MC', role: 'MC', voice_fishs2pro: null, voice_aivispeech: null, voice_voicevox: null, is_active: true, created_at: NOW, updated_at: NOW },
  ]
}

function reset() {
  programs = [sampleProgram()]
  mcs = initialMcs()
  mutations = []
}
reset()

function send(response, status, body, headers = {}) {
  response.writeHead(status, { 'Content-Type': 'application/json', ...headers })
  response.end(body === undefined ? '' : JSON.stringify(body))
}

function authorized(request) {
  return request.headers.cookie?.split(';').some((value) => value.trim() === 'admin_session=e2e-session')
}

function requireAuth(request, response) {
  if (authorized(request)) return true
  send(response, 401, { detail: '認証されていません' })
  return false
}

function parseBody(request) {
  return new Promise((resolve, reject) => {
    let body = ''
    request.on('data', (chunk) => { body += chunk })
    request.on('end', () => {
      try { resolve(body ? JSON.parse(body) : {}) } catch (error) { reject(error) }
    })
    request.on('error', reject)
  })
}

function upsertProgram(id, definition, isActive) {
  const existing = programs.find((program) => program.id === id)
  const program = {
    id, name: definition.name, kind: definition.kind, definition: { ...definition, id },
    is_active: Boolean(isActive), created_at: existing?.created_at ?? NOW, updated_at: NOW,
  }
  if (existing) programs = programs.map((entry) => entry.id === id ? program : entry)
  else programs.push(program)
  return program
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, `http://${request.headers.host}`)
  const path = url.pathname

  if (request.method === 'GET' && path === '/__health') return send(response, 200, { ok: true })
  if (path === '/__reset' && request.method === 'POST') {
    reset()
    return send(response, 200, { ok: true })
  }
  if (path === '/__state' && request.method === 'GET') return send(response, 200, { mutations, programs, mcs })
  if (path === '/admin/login' && request.method === 'POST') {
    const body = await parseBody(request)
    if (body.username !== 'admin' || body.password !== 'password') return send(response, 401, { detail: 'invalid credentials' })
    return send(response, 200, { ok: true }, { 'Set-Cookie': 'admin_session=e2e-session; Path=/; HttpOnly; SameSite=Lax' })
  }
  if (path === '/admin/me' && request.method === 'GET') {
    if (!authorized(request)) return send(response, 401, { detail: '認証されていません' })
    return send(response, 200, { username: 'admin' })
  }
  if (!path.startsWith('/admin/')) return send(response, 404, { detail: 'not found' })
  if (!requireAuth(request, response)) return

  if (path === '/admin/programs' && request.method === 'GET') {
    const list = url.searchParams.get('include_inactive') === 'true' ? programs : programs.filter((entry) => entry.is_active)
    return send(response, 200, list)
  }
  if (path === '/admin/programs' && request.method === 'POST') {
    const body = await parseBody(request)
    mutations.push({ method: 'POST', resource: 'program', body })
    if (programs.some((program) => program.id === body.id)) return send(response, 409, { detail: '番組IDは既に使用されています' })
    if (body.cast?.some((member) => member.mc_id && !validMcIds.has(member.mc_id))) return send(response, 422, { detail: 'MC参照が無効です' })
    return send(response, 201, upsertProgram(body.id, body, body.is_active))
  }
  const programMatch = path.match(/^\/admin\/programs\/([^/]+)$/)
  if (programMatch && request.method === 'GET') {
    const program = programs.find((entry) => entry.id === decodeURIComponent(programMatch[1]))
    return program ? send(response, 200, program) : send(response, 404, { detail: '番組が見つかりません' })
  }
  if (programMatch && request.method === 'PUT') {
    const id = decodeURIComponent(programMatch[1])
    const body = await parseBody(request)
    mutations.push({ method: 'PUT', resource: 'program', id, body })
    if (body.cast?.some((member) => member.mc_id && !validMcIds.has(member.mc_id))) return send(response, 422, { detail: 'MC参照が無効です' })
    if (!programs.some((program) => program.id === id)) return send(response, 404, { detail: '番組が見つかりません' })
    return send(response, 200, upsertProgram(id, body, body.is_active))
  }

  if (path === '/admin/mcs' && request.method === 'GET') {
    const list = url.searchParams.get('include_inactive') === 'true' ? mcs : mcs.filter((mc) => mc.is_active)
    return send(response, 200, list)
  }
  if (path === '/admin/mcs' && request.method === 'POST') {
    const body = await parseBody(request)
    mutations.push({ method: 'POST', resource: 'mc', body })
    if (mcs.some((mc) => mc.id === body.id)) return send(response, 409, { detail: 'MC IDは既に使用されています' })
    const mc = { ...body, created_at: NOW, updated_at: NOW }
    mcs.push(mc)
    return send(response, 201, mc)
  }
  const mcMatch = path.match(/^\/admin\/mcs\/([^/]+)$/)
  if (mcMatch && request.method === 'PUT') {
    const id = decodeURIComponent(mcMatch[1])
    const body = await parseBody(request)
    mutations.push({ method: 'PUT', resource: 'mc', id, body })
    if (!mcs.some((mc) => mc.id === id)) return send(response, 404, { detail: 'MCが見つかりません' })
    const mc = { ...body, id, created_at: mcs.find((entry) => entry.id === id).created_at, updated_at: NOW }
    mcs = mcs.map((entry) => entry.id === id ? mc : entry)
    return send(response, 200, mc)
  }
  return send(response, 404, { detail: 'not found' })
})

server.listen(PORT, '127.0.0.1')
