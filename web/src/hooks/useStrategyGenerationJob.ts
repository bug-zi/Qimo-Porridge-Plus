import { useCallback, useEffect, useRef, useState } from 'react'
import {
  cancelAgentJob,
  getActiveStrategyGenerationJob,
  getAgentJob,
} from '../apiClient'
import type { AgentJob, StrategyGenerationSession } from '../types'

const ACTIVE_STATUSES = new Set<AgentJob['status']>(['queued', 'running'])
const NORMAL_POLL_MS = 2_000
const MAX_BACKOFF_MS = 15_000

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback
}

function nextDelay(failures: number) {
  if (failures <= 1) return NORMAL_POLL_MS
  return Math.min(MAX_BACKOFF_MS, NORMAL_POLL_MS * (2 ** (failures - 1)))
}

function workspaceFingerprint(job: AgentJob) {
  const current = job.modelUsage?.currentCall
  return [job.status, job.updatedAt, job.progress?.updatedAt, job.progress?.stage, job.progress?.taskId,
    job.modelUsage?.updatedAt, current?.stage, current?.taskId, current?.attempt].join('|')
}

export function useStrategyGenerationJob(
  courseId: string | null,
  refreshWorkspace: (courseId: string) => Promise<void>,
) {
  const [session, setSession] = useState<StrategyGenerationSession | null>(null)
  const generationRef = useRef(0)
  const sessionRef = useRef(session)
  const lastWorkspaceFingerprintRef = useRef('')
  sessionRef.current = session

  const refreshWorkspaceSafely = useCallback(async (targetCourseId: string, jobId: string) => {
    try {
      await refreshWorkspace(targetCourseId)
      setSession((current) => current?.job.id === jobId ? { ...current, workspaceRefreshError: '' } : current)
      return true
    } catch (error) {
      setSession((current) => current?.job.id === jobId
        ? { ...current, workspaceRefreshError: errorMessage(error, '课程内容预览刷新失败') }
        : current)
      return false
    }
  }, [refreshWorkspace])

  const acceptJob = useCallback((targetCourseId: string, job: AgentJob, source: StrategyGenerationSession['source']) => {
    setSession((current) => ({
      courseId: targetCourseId,
      job,
      source: current?.job.id === job.id ? current.source : source,
      syncStatus: 'healthy',
      consecutiveSyncFailures: 0,
      lastSyncedAt: new Date().toISOString(),
      syncError: '',
      workspaceRefreshError: current?.job.id === job.id ? current.workspaceRefreshError : '',
      stopRequested: current?.job.id === job.id && ACTIVE_STATUSES.has(job.status) ? current.stopRequested : false,
    }))
  }, [])

  const submitJob = useCallback((targetCourseId: string, job: AgentJob) => {
    lastWorkspaceFingerprintRef.current = ''
    acceptJob(targetCourseId, job, 'submitted')
  }, [acceptJob])

  const refresh = useCallback(async () => {
    const current = sessionRef.current
    if (!courseId) return
    const job = current?.courseId === courseId ? current.job : null
    setSession((value) => value?.courseId === courseId ? { ...value, syncStatus: 'syncing' } : value)
    let freshJob: AgentJob | null
    try {
      freshJob = job
        ? await getAgentJob(job.id)
        : (await getActiveStrategyGenerationJob(courseId)).job
      if (freshJob) acceptJob(courseId, freshJob, job ? current?.source ?? 'recovered' : 'recovered')
    } catch (error) {
      setSession((value) => {
        if (!value || value.courseId !== courseId) return value
        const failures = value.consecutiveSyncFailures + 1
        return { ...value, consecutiveSyncFailures: failures, syncStatus: failures >= 3 ? 'offline' : 'degraded', syncError: errorMessage(error, '生成状态同步失败') }
      })
      throw error
    }
    if (freshJob) await refreshWorkspaceSafely(courseId, freshJob.id)
    else await refreshWorkspace(courseId)
  }, [acceptJob, courseId, refreshWorkspace, refreshWorkspaceSafely])

  const requestStop = useCallback(async () => {
    const current = sessionRef.current
    if (!current || !ACTIVE_STATUSES.has(current.job.status)) return
    setSession((value) => value?.job.id === current.job.id ? { ...value, stopRequested: true } : value)
    try {
      const job = await cancelAgentJob(current.job.id)
      acceptJob(current.courseId, job, current.source)
      if (ACTIVE_STATUSES.has(job.status)) {
        setSession((value) => value?.job.id === job.id ? { ...value, stopRequested: true } : value)
      }
      await refreshWorkspaceSafely(current.courseId, job.id)
    } catch (error) {
      setSession((value) => value?.job.id === current.job.id
        ? { ...value, stopRequested: false, syncError: errorMessage(error, '停止请求提交失败') }
        : value)
      throw error
    }
  }, [acceptJob, refreshWorkspaceSafely])

  const trackedJobId = session?.courseId === courseId ? session.job.id : ''

  useEffect(() => {
    const generation = ++generationRef.current
    lastWorkspaceFingerprintRef.current = ''
    if (!courseId) {
      setSession(null)
      return
    }
    setSession((current) => current?.courseId === courseId ? current : null)
    let timer: number | undefined
    let failures = 0

    const schedule = (delay: number) => {
      if (generation === generationRef.current) timer = window.setTimeout(() => void poll(), delay)
    }
    const poll = async () => {
      if (generation !== generationRef.current) return
      const current = sessionRef.current
      try {
        const job = current?.courseId === courseId
          ? await getAgentJob(current.job.id)
          : (await getActiveStrategyGenerationJob(courseId)).job
        if (generation !== generationRef.current) return
        failures = 0
        if (!job) return
        acceptJob(courseId, job, current?.job.id === job.id ? current.source : 'recovered')
        const fingerprint = workspaceFingerprint(job)
        if (fingerprint !== lastWorkspaceFingerprintRef.current || !ACTIVE_STATUSES.has(job.status)) {
          if (await refreshWorkspaceSafely(courseId, job.id)) lastWorkspaceFingerprintRef.current = fingerprint
        }
        if (ACTIVE_STATUSES.has(job.status)) schedule(NORMAL_POLL_MS)
      } catch (error) {
        if (generation !== generationRef.current) return
        failures += 1
        setSession((value) => {
          if (!value || value.courseId !== courseId) return value
          return { ...value, consecutiveSyncFailures: failures, syncStatus: failures >= 3 ? 'offline' : 'degraded', syncError: errorMessage(error, '生成状态同步失败') }
        })
        schedule(nextDelay(failures))
      }
    }
    void poll()
    return () => {
      generationRef.current += 1
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [acceptJob, courseId, refreshWorkspaceSafely, trackedJobId])

  return { session, submitJob, refresh, requestStop }
}
