/** 课程术语词条状态：持续同步已落库词条，生成期间按批次实时展示。 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import type { GlossaryStatus, GlossaryTerm } from '../types'
import { getAgentJob, getCourseGlossary, refreshCourseGlossary } from '../apiClient'
import { clearGlossaryTerms, setActiveGlossaryTerms } from '../glossary/termMatcher'
import GlossaryTermCard from '../components/GlossaryTermCard'

type GlossaryContextValue = {
  terms: GlossaryTerm[]
  status: GlossaryStatus | null
  activeTermId: string | null
  openTerm: (termId: string) => void
  closeTerm: () => void
  refresh: (force?: boolean) => Promise<void>
  syncNow: () => Promise<void>
  isRefreshing: boolean
}

const GlossaryContext = createContext<GlossaryContextValue | null>(null)
const SYNC_INTERVAL_MS = 1500

export function useGlossary(): GlossaryContextValue {
  const context = useContext(GlossaryContext)
  if (!context) {
    return {
      terms: [], status: null, activeTermId: null, openTerm: () => {}, closeTerm: () => {},
      refresh: async () => {}, syncNow: async () => {}, isRefreshing: false,
    }
  }
  return context
}

export function GlossaryProvider({ courseId, children }: { courseId: string | null; children: ReactNode }) {
  const [terms, setTerms] = useState<GlossaryTerm[]>([])
  const [status, setStatus] = useState<GlossaryStatus | null>(null)
  const [activeTermId, setActiveTermId] = useState<string | null>(null)
  const [glossaryJobId, setGlossaryJobId] = useState<string | null>(null)
  const pollTimerRef = useRef<number | null>(null)
  const syncInFlightRef = useRef(false)
  const courseIdRef = useRef(courseId)
  const jobIdRef = useRef<string | null>(null)

  useEffect(() => { courseIdRef.current = courseId }, [courseId])
  useEffect(() => { jobIdRef.current = glossaryJobId }, [glossaryJobId])

  const applyGlossary = useCallback((id: string, response: Awaited<ReturnType<typeof getCourseGlossary>>) => {
    if (courseIdRef.current !== id) return
    setTerms(response.terms)
    setStatus(response.status)
    setActiveGlossaryTerms(response.terms)
    setActiveTermId((current) => current && response.terms.some((term) => term.id === current) ? current : null)
  }, [])

  const loadGlossary = useCallback(async (id: string) => {
    if (syncInFlightRef.current) return null
    syncInFlightRef.current = true
    try {
      const response = await getCourseGlossary(id)
      applyGlossary(id, response)
      return response
    } finally {
      syncInFlightRef.current = false
    }
  }, [applyGlossary])

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current)
    pollTimerRef.current = null
  }, [])

  const poll = useCallback(async function runPoll() {
    const id = courseIdRef.current
    if (!id) return
    try {
      const [response, job] = await Promise.all([
        loadGlossary(id),
        jobIdRef.current ? getAgentJob(jobIdRef.current).catch(() => null) : Promise.resolve(null),
      ])
      if (courseIdRef.current !== id) return
      const serverGenerating = response?.status.status === 'generating'
      const jobRunning = job?.status === 'queued' || job?.status === 'running'
      if (job && (job.status === 'completed' || job.status === 'failed')) {
        setGlossaryJobId(null)
        jobIdRef.current = null
      }
      if (!serverGenerating && !jobRunning) {
        stopPolling()
        return
      }
    } catch {
      // 短暂网络错误不清空已生成词条；下一轮继续同步。
    }
    stopPolling()
    pollTimerRef.current = window.setTimeout(() => void runPoll(), SYNC_INTERVAL_MS)
  }, [loadGlossary, stopPolling])

  const startPolling = useCallback(() => {
    stopPolling()
    pollTimerRef.current = window.setTimeout(() => void poll(), 0)
  }, [poll, stopPolling])

  useEffect(() => {
    stopPolling()
    setGlossaryJobId(null)
    jobIdRef.current = null
    if (!courseId) {
      setTerms([])
      setStatus(null)
      clearGlossaryTerms()
      return
    }
    setTerms([])
    setStatus(null)
    clearGlossaryTerms()
    void loadGlossary(courseId).then((response) => {
      if (response?.status.status === 'generating') startPolling()
    }).catch(() => {})
    return stopPolling
  }, [courseId, loadGlossary, startPolling, stopPolling])

  const syncNow = useCallback(async () => {
    if (!courseId) return
    try {
      const response = await loadGlossary(courseId)
      if (response?.status.status === 'generating') startPolling()
    } catch {
      // 手动同步失败时保留当前词条。
    }
  }, [courseId, loadGlossary, startPolling])

  const refresh = useCallback(async (force = false) => {
    if (!courseId) return
    const current = await loadGlossary(courseId).catch(() => null)
    if (current?.status.status === 'generating' || jobIdRef.current) {
      startPolling()
      return
    }
    try {
      setStatus((existing) => existing
        ? { ...existing, status: 'generating', phase: 'scanning', lastError: '' }
        : {
            courseId, status: 'generating', phase: 'scanning', termsTotal: 0, termsActive: 0,
            candidatesTotal: 0, termsCompleted: 0, lastError: '', lastRefreshedAt: '',
            startedAt: new Date().toISOString(), progressUpdatedAt: new Date().toISOString(),
          })
      const { jobId } = await refreshCourseGlossary(courseId, force)
      setGlossaryJobId(jobId)
      jobIdRef.current = jobId
      startPolling()
    } catch (error) {
      setGlossaryJobId(null)
      jobIdRef.current = null
      setStatus((existing) => existing
        ? { ...existing, status: 'failed', phase: 'failed', lastError: error instanceof Error ? error.message : '术语生成请求失败' }
        : null)
    }
  }, [courseId, loadGlossary, startPolling])

  useEffect(() => stopPolling, [stopPolling])

  const openTerm = useCallback((termId: string) => setActiveTermId(termId), [])
  const closeTerm = useCallback(() => setActiveTermId(null), [])
  const activeTerm = useMemo(() => terms.find((term) => term.id === activeTermId) ?? null, [terms, activeTermId])
  const isRefreshing = glossaryJobId !== null || status?.status === 'generating'
  const value = useMemo(
    () => ({ terms, status, activeTermId, openTerm, closeTerm, refresh, syncNow, isRefreshing }),
    [terms, status, activeTermId, openTerm, closeTerm, refresh, syncNow, isRefreshing],
  )

  return (
    <GlossaryContext.Provider value={value}>
      {children}
      {activeTerm ? <GlossaryTermCard term={activeTerm} onClose={closeTerm} /> : null}
    </GlossaryContext.Provider>
  )
}
