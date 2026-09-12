/** Типизированный клиент API «Моисея». */

export interface Meta {
  app: { name: string; subtitle: string; region: string }
  stats: {
    services: number; chunks: number; departments: number; branches: number
    lifeSituations: number; vocabulary: number; builtAt: number
    buildSeconds: number; rawBytes: number; cleanBytes: number; noiseRemovedPct: number
  }
  llm: { enabled: boolean; mode: 'llm' | 'extractive'; model: string | null }
  sections: { code: string; label: string; short: string; icon: string }[]
  departments: { id: string; name: string; shortName?: string; count: number }[]
  lifeSituations: { id: string; name: string; count: number }[]
  recipients: { id: string; name: string; count: number }[]
  branchesCount: number
}

export interface QueryAnalysis {
  raw: string; normalized: string; tokens: string[]; expansionTokens: string[]
  hints: string[]; layoutFixed: boolean; corrections: { from: string; to: string }[]
}

export interface ServiceBrief {
  id: string; title: string; shortTitle: string
  department: string | null; departmentId: string | null
  recipients: string[]; lifeSituations: string[]
  branchCount: number; completeness: number; missingSections: string[]
  flags: string[]; snippet: string; matchedSections: string[]
  bestSection: string | null; score: number
  variantGroup: string | null; variantLabel: string | null
  variantCount?: number; variantTotal?: number
}

export interface Block { kind: string; text: string; marker?: string; level?: number }
export interface Section {
  code: string; label: string; text: string; blocks: Block[]
  links: { href: string; title: string }[]
}
export interface Branch {
  id: string; name: string; address: string | null; schedule: string[]
  code?: string | null; windowCount?: string | null
}
export interface ServiceCard extends ServiceBrief {
  sections: Section[]; branches: Branch[]; similar: string[]; hasRaw: string[]
  variants: { id: string; label: string; department: string | null; current: boolean }[]
}

export interface SearchResponse {
  query: string; total: number; took: number
  analysis: QueryAnalysis | null; results: ServiceBrief[]
}

export interface Fragment {
  serviceId: string; serviceTitle: string; serviceShort: string
  department: string | null; section: string; sectionLabel: string
  text: string; chunkId: string; score: number
}

export interface AskResponse {
  answer: string; fragments: Fragment[]; citations: number[]
  analysis: QueryAnalysis; mode: string; cached: boolean; model: string
  latencyMs: number; tokensIn: number; tokensOut: number
  detectedIntent: string | null
  services: { id: string; title: string; shortTitle: string; department: string | null }[]
  warning: string | null
}

export interface ScenarioBrief {
  id: string; title: string; subtitle: string; emoji: string
  steps: number; lifeSituations: string[]
}
export interface ScenarioStep {
  id: string; question: string; hint: string; multi: boolean
  options: { id: string; label: string }[]
}
export interface Scenario {
  id: string; title: string; subtitle: string; emoji: string; steps: ScenarioStep[]
}
export interface ChecklistItem {
  id: string | null; text: string; critical: boolean
  services: string[]; count: number; wordings: string[]
}
export interface WizardPackage {
  scenarioId: string; title: string; emoji: string
  answers: { step: string; answer: string }[]
  services: {
    id: string; title: string; shortTitle: string; department: string | null
    stage: number; reasons: string[]; term: string; payment: string; isFree: boolean
    completeness: number; missingSections: string[]; score: number
    variantLabel: string | null; variantCount: number
  }[]
  checklist: { common: ChecklistItem[]; specific: ChecklistItem[]; totalUnique: number }
  summary: {
    servicesCount: number; departments: string[]; departmentsCount: number
    freeCount: number; commonDocs: number; visitsHint: string
  }
  memo: string; memoCached?: boolean; llmAvailable: boolean
}

export interface CacheStats {
  entries: number; hits: number; misses: number; hitRate: number
  savedTokensIn: number; savedTokensOut: number; savedUsd: number; savedSeconds: number
  top: { question: string; service_id: string | null; hits: number; kind: string }[]
  recent: { ts: number; kind: string; service_id: string | null; question: string; cached: number }[]
  model: string; mode: string; ttlDays: number
}

export interface QualityReport {
  services: number
  sections: { code: string; label: string; filled: number; empty: number; fillRate: number; withHtml: number }[]
  completeness: { full: number; partial: number; poor: number }
  worst: { id: string; title: string; completeness: number; missing: string[]; department: string | null }[]
  noLifeSituation: number; noBranches: number; missingDepartment: number
  unknownDepartmentIds: string[]; unknownBranchIds: string[]; unknownBranchCount: number
  imagesDropped: number; rawBytes: number; cleanBytes: number; noiseRemovedPct: number
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`${res.status}: ${detail.slice(0, 200)}`)
  }
  return res.json() as Promise<T>
}

export interface SearchFilters {
  department?: string[]; lifeSituation?: string[]
  recipient?: string[]; branch?: string[]
}

function filterParams(f: SearchFilters | undefined, p: URLSearchParams) {
  if (!f) return
  f.department?.forEach((v) => p.append('department', v))
  f.lifeSituation?.forEach((v) => p.append('lifeSituation', v))
  f.recipient?.forEach((v) => p.append('recipient', v))
  f.branch?.forEach((v) => p.append('branch', v))
}

export const api = {
  meta: () => json<Meta>('/api/meta'),

  search: (q: string, filters?: SearchFilters, limit = 20, groupVariants = true) => {
    const p = new URLSearchParams({ q, limit: String(limit), groupVariants: String(groupVariants) })
    filterParams(filters, p)
    return json<SearchResponse>(`/api/search?${p}`)
  },

  service: (id: string) => json<ServiceCard>(`/api/services/${encodeURIComponent(id)}`),

  raw: (id: string, section: string) =>
    json<{ raw: string; length: number }>(
      `/api/services/${encodeURIComponent(id)}/raw/${encodeURIComponent(section)}`,
    ),

  ask: (question: string, serviceId?: string | null, useCache = true) =>
    json<AskResponse>('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, serviceId: serviceId ?? null, useCache }),
    }),

  scenarios: () => json<ScenarioBrief[]>('/api/wizard/scenarios'),
  scenario: (id: string) => json<Scenario>(`/api/wizard/scenarios/${id}`),
  wizardPackage: (scenarioId: string, answers: Record<string, string[]>) =>
    json<WizardPackage>('/api/wizard/package', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenarioId, answers, withMemo: true }),
    }),

  cacheStats: () => json<CacheStats>('/api/cache/stats'),
  cacheClear: () => json<{ removed: number }>('/api/cache/clear', { method: 'POST' }),
  quality: () => json<QualityReport>('/api/quality'),
  branches: (q = '') => json<(Branch & { count: number })[]>(`/api/branches?q=${encodeURIComponent(q)}`),
}

/** Стрим ответа Моисея через SSE. Возвращает функцию отмены. */
export function askStream(
  question: string,
  serviceId: string | null,
  handlers: {
    onMeta?: (m: { analysis: QueryAnalysis; fragments: Fragment[]; detectedIntent: string | null; mode: string }) => void
    onDelta?: (t: string) => void
    onDone?: (d: Record<string, unknown>) => void
    onError?: (e: string) => void
  },
): () => void {
  const p = new URLSearchParams({ q: question })
  if (serviceId) p.set('serviceId', serviceId)
  const es = new EventSource(`/api/ask/stream?${p}`)
  let finished = false

  es.onmessage = (ev) => {
    let payload: any
    try {
      payload = JSON.parse(ev.data)
    } catch {
      return
    }
    if (payload.type === 'meta') handlers.onMeta?.(payload)
    else if (payload.type === 'delta') handlers.onDelta?.(payload.text)
    else if (payload.type === 'error') {
      handlers.onError?.(payload.message)
      finished = true
      es.close()
    } else if (payload.type === 'done') {
      finished = true
      handlers.onDone?.(payload)
      es.close()
    }
  }
  es.onerror = () => {
    if (!finished) handlers.onError?.('Соединение с сервером прервано')
    es.close()
  }
  return () => {
    finished = true
    es.close()
  }
}
