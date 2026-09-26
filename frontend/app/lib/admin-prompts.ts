import { extractErrorMessage } from './admin-programs'

export type PromptVersionStatus = 'draft' | 'active' | 'archived'

export interface PromptVersionSummary {
  id: number
  version: number
  status: PromptVersionStatus
  created_at: string
  updated_at: string
}

export interface PromptTemplate {
  id: number
  template_key: string
  program_id: string | null
  required_variables: string[]
  allowed_variables: string[]
  versions: PromptVersionSummary[]
}

export interface PromptVersionDetail extends PromptVersionSummary {
  content: string
}

export interface PromptVersionsResponse {
  prompt_id: number
  template_key: string
  program_id: string | null
  versions: PromptVersionDetail[]
}

export interface PromptTemplateCreateInput {
  template_key: string
  program_id: string
}

/** create_prompt_versionのAPI応答はcreated_at/updated_atを含まないため、一覧取得用の型とは分けている。 */
export interface PromptVersionCreateResult {
  id: number
  template_id: number
  version: number
  content: string
  status: PromptVersionStatus
}

export interface PromptRenderResult {
  version_id: number
  episode_id: number
  template_key: string
  prompt: string
}

export interface PromptPreviewResult {
  program_id: string
  episode_id: number
  template_key: string
  version_id: number
  prompt: string
}

export interface PromptActivateResult {
  id: number
  status: 'active'
  previous_active_version_id: number | null
}

export interface PromptRollbackResult {
  id: number
  version: number
  status: 'active'
  rollback_from_version_id: number
  previous_active_version_id: number | null
}

export interface ChangeInput {
  change_note: string
  expected_active_version_id: number | null
}

export class PromptApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'PromptApiError'
    this.status = status
  }
}

const SERVER_API_BASE = process.env.API_BASE ?? 'http://api:8010'

function toQueryString(params: Record<string, string | undefined>): string {
  const parts: string[] = []
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined && val !== '') {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(val)}`)
    }
  }
  return parts.length ? `?${parts.join('&')}` : ''
}

async function serverHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const { cookies } = await import('next/headers')
  const cookie = (await cookies()).get('admin_session')?.value
  if (cookie) headers['Cookie'] = `admin_session=${cookie}`
  return headers
}

async function serverFetch(path: string, options?: RequestInit): Promise<Response> {
  const headers = await serverHeaders()
  return fetch(`${SERVER_API_BASE}${path}`, {
    ...options,
    headers: { ...headers, ...(options?.headers as Record<string, string>) },
  })
}

async function clientFetch(path: string, options?: RequestInit): Promise<Response> {
  return fetch(`/api${path}`, options)
}

export async function fetchPrompts(programId?: string): Promise<PromptTemplate[]> {
  const qs = toQueryString({ program_id: programId })
  const isServer = typeof window === 'undefined'
  const res = await (isServer
    ? serverFetch(`/admin/prompts${qs}`, { cache: 'no-store' })
    : clientFetch(`/admin/prompts${qs}`, { cache: 'no-store' }))
  if (!res.ok) throw new Error(await extractErrorMessage(res))
  return res.json() as Promise<PromptTemplate[]>
}

export async function fetchPromptVersions(promptId: number): Promise<PromptVersionsResponse> {
  const isServer = typeof window === 'undefined'
  const res = await (isServer
    ? serverFetch(`/admin/prompts/${promptId}/versions`, { cache: 'no-store' })
    : clientFetch(`/admin/prompts/${promptId}/versions`, { cache: 'no-store' }))
  if (!res.ok) throw new Error(await extractErrorMessage(res))
  return res.json() as Promise<PromptVersionsResponse>
}

export async function createPromptTemplate(input: PromptTemplateCreateInput): Promise<PromptTemplate> {
  const res = await clientFetch('/admin/prompts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error(await extractErrorMessage(res))
  return res.json() as Promise<PromptTemplate>
}

export async function createPromptVersion(promptId: number, content: string): Promise<PromptVersionCreateResult> {
  const res = await clientFetch(`/admin/prompts/${promptId}/versions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
  if (!res.ok) throw new Error(await extractErrorMessage(res))
  return res.json() as Promise<PromptVersionCreateResult>
}

export async function renderPromptVersion(versionId: number, episodeId: number): Promise<PromptRenderResult> {
  const res = await clientFetch(`/admin/prompts/versions/${versionId}/render`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ episode_id: episodeId }),
  })
  if (!res.ok) throw new PromptApiError(res.status, await extractErrorMessage(res))
  return res.json() as Promise<PromptRenderResult>
}

export async function previewProgramPrompt(
  programId: string,
  templateKey: string,
  episodeId: number,
): Promise<PromptPreviewResult> {
  const res = await clientFetch(`/admin/programs/${encodeURIComponent(programId)}/preview-prompt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template_key: templateKey, episode_id: episodeId }),
  })
  if (!res.ok) throw new PromptApiError(res.status, await extractErrorMessage(res))
  return res.json() as Promise<PromptPreviewResult>
}

export async function activatePromptVersion(versionId: number, input: ChangeInput): Promise<PromptActivateResult> {
  const res = await clientFetch(`/admin/prompts/versions/${versionId}/activate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new PromptApiError(res.status, await extractErrorMessage(res))
  return res.json() as Promise<PromptActivateResult>
}

export async function rollbackPromptVersion(versionId: number, input: ChangeInput): Promise<PromptRollbackResult> {
  const res = await clientFetch(`/admin/prompts/versions/${versionId}/rollback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new PromptApiError(res.status, await extractErrorMessage(res))
  return res.json() as Promise<PromptRollbackResult>
}
