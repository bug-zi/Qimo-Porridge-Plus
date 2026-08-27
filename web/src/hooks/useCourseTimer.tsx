import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from 'react'

export type CourseTimerState = {
  courseId: string
  courseName: string
  elapsedSec: number
  running: boolean
}

type TimerSession = CourseTimerState & {
  id: string
  accumulatedMs: number
  startedAt: number | null
}

type PendingRecord = {
  id: string
  courseId: string
  courseName: string
  minutes: number
}

type CourseTimerContextValue = {
  timer: CourseTimerState | null
  recording: boolean
  start: (courseId: string, courseName: string) => void
  toggle: () => void
  stopAndRecord: () => Promise<void>
  discard: () => void
  backfill: (minutes: number) => Promise<void>
}

const CourseTimerContext = createContext<CourseTimerContextValue | null>(null)
const MAX_RECORD_MINUTES = 1440

function createSession(courseId: string, courseName: string): TimerSession {
  return {
    id: `timer-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    courseId,
    courseName,
    elapsedSec: 0,
    accumulatedMs: 0,
    startedAt: Date.now(),
    running: true,
  }
}

function elapsedMs(session: TimerSession, now = Date.now()): number {
  return session.accumulatedMs + (session.running && session.startedAt ? Math.max(0, now - session.startedAt) : 0)
}

function publicTimer(session: TimerSession | null, now = Date.now()): CourseTimerState | null {
  if (!session) return null
  return { ...session, elapsedSec: Math.floor(elapsedMs(session, now) / 1000) }
}

/** 顶栏自动计时；关闭时的未确认提交会使用同一 client id 在下次进入时重试。 */
export function CourseTimerProvider({
  children,
  activeCourseId,
  activeCourseName,
  userId,
  onRecordMinutes,
  onFlushMinutes,
  finalizeRef,
}: {
  children: ReactNode
  activeCourseId: string
  activeCourseName: string
  userId: string
  onRecordMinutes: (courseId: string, courseName: string, minutes: number, clientEntryId?: string) => Promise<void>
  onFlushMinutes: (courseId: string, minutes: number, clientEntryId: string) => void
  finalizeRef?: MutableRefObject<(() => Promise<void>) | null>
}) {
  const [session, setSession] = useState<TimerSession | null>(null)
  const [displayTimer, setDisplayTimer] = useState<CourseTimerState | null>(null)
  const [recording, setRecording] = useState(false)
  const sessionRef = useRef<TimerSession | null>(null)
  const submittingRef = useRef(new Set<string>())
  const recordMinutesRef = useRef(onRecordMinutes)
  const flushMinutesRef = useRef(onFlushMinutes)
  const storageKey = `final-congee-course-timer-pending:${userId || 'anonymous'}`

  useEffect(() => {
    recordMinutesRef.current = onRecordMinutes
    flushMinutesRef.current = onFlushMinutes
  }, [onRecordMinutes, onFlushMinutes])

  const replaceSession = useCallback((next: TimerSession | null) => {
    sessionRef.current = next
    setSession(next)
    setDisplayTimer(publicTimer(next))
  }, [])

  const readPending = useCallback((): PendingRecord[] => {
    try {
      const parsed = JSON.parse(window.localStorage.getItem(storageKey) || '[]')
      return Array.isArray(parsed) ? parsed.filter((item): item is PendingRecord =>
        Boolean(item && typeof item.id === 'string' && typeof item.courseId === 'string' && Number.isInteger(item.minutes) && item.minutes > 0),
      ) : []
    } catch {
      return []
    }
  }, [storageKey])

  const writePending = useCallback((items: PendingRecord[]) => {
    try {
      if (items.length) window.localStorage.setItem(storageKey, JSON.stringify(items))
      else window.localStorage.removeItem(storageKey)
    } catch {
      // 本地存储不可用不应中断学习界面。
    }
  }, [storageKey])

  const enqueue = useCallback((record: PendingRecord) => {
    const pending = readPending()
    if (!pending.some((item) => item.id === record.id)) writePending([...pending, record])
  }, [readPending, writePending])

  const removePending = useCallback((id: string) => {
    writePending(readPending().filter((item) => item.id !== id))
  }, [readPending, writePending])

  const submitRecord = useCallback(async (record: PendingRecord) => {
    if (submittingRef.current.has(record.id)) return
    submittingRef.current.add(record.id)
    setRecording(true)
    try {
      await recordMinutesRef.current(record.courseId, record.courseName, record.minutes, record.id)
      removePending(record.id)
    } finally {
      submittingRef.current.delete(record.id)
      setRecording(submittingRef.current.size > 0)
    }
  }, [removePending])

  const recordSession = useCallback(async (current: TimerSession | null) => {
    if (!current) return
    const minutes = Math.min(MAX_RECORD_MINUTES, Math.floor(elapsedMs(current) / 60000))
    if (minutes <= 0) return
    const record = { id: current.id, courseId: current.courseId, courseName: current.courseName, minutes }
    enqueue(record)
    await submitRecord(record)
  }, [enqueue, submitRecord])

  useEffect(() => {
    for (const pending of readPending()) void submitRecord(pending).catch(() => undefined)
  }, [readPending, submitRecord])

  useEffect(() => {
    if (!activeCourseId) return
    const current = sessionRef.current
    if (current?.courseId === activeCourseId) return
    if (current) void recordSession(current).catch(() => undefined)
    replaceSession(createSession(activeCourseId, activeCourseName))
  }, [activeCourseId, activeCourseName, recordSession, replaceSession])

  useEffect(() => {
    setDisplayTimer(publicTimer(sessionRef.current))
    if (!session?.running) return
    const id = window.setInterval(() => setDisplayTimer(publicTimer(sessionRef.current)), 1000)
    return () => window.clearInterval(id)
  }, [session?.id, session?.running])

  const start = useCallback((courseId: string, courseName: string) => {
    const current = sessionRef.current
    if (current?.courseId === courseId) {
      if (!current.running) replaceSession({ ...current, running: true, startedAt: Date.now() })
      return
    }
    if (current) void recordSession(current).catch(() => undefined)
    replaceSession(createSession(courseId, courseName))
  }, [recordSession, replaceSession])

  const toggle = useCallback(() => {
    const current = sessionRef.current
    if (!current) return
    if (current.running) replaceSession({ ...current, accumulatedMs: elapsedMs(current), startedAt: null, running: false })
    else replaceSession({ ...current, startedAt: Date.now(), running: true })
  }, [replaceSession])

  const stopAndRecord = useCallback(async () => {
    const current = sessionRef.current
    if (!current) return
    replaceSession(createSession(current.courseId, current.courseName))
    await recordSession(current)
  }, [recordSession, replaceSession])

  const discard = useCallback(() => {
    // 用户点击 × 明确退出计时；只有手动点击“开始计时”或切换课程才重新开始。
    replaceSession(null)
  }, [replaceSession])

  const backfill = useCallback(async (minutes: number) => {
    const current = sessionRef.current
    if (!current) return
    const safe = Math.max(1, Math.min(MAX_RECORD_MINUTES, Math.round(minutes)))
    const record = { id: `timer-${Date.now()}-backfill`, courseId: current.courseId, courseName: current.courseName, minutes: safe }
    enqueue(record)
    await submitRecord(record)
  }, [enqueue, submitRecord])

  const finalize = useCallback(async () => {
    const current = sessionRef.current
    replaceSession(null)
    await recordSession(current)
  }, [recordSession, replaceSession])

  useEffect(() => {
    if (!finalizeRef) return
    finalizeRef.current = finalize
    return () => {
      if (finalizeRef.current === finalize) finalizeRef.current = null
    }
  }, [finalize, finalizeRef])

  useEffect(() => {
    const handlePageHide = () => {
      const current = sessionRef.current
      if (!current) return
      const minutes = Math.min(MAX_RECORD_MINUTES, Math.floor(elapsedMs(current) / 60000))
      if (minutes <= 0) return
      const record = { id: current.id, courseId: current.courseId, courseName: current.courseName, minutes }
      enqueue(record)
      flushMinutesRef.current(record.courseId, record.minutes, record.id)
    }
    window.addEventListener('pagehide', handlePageHide)
    return () => window.removeEventListener('pagehide', handlePageHide)
  }, [enqueue])

  return (
    <CourseTimerContext.Provider value={{ timer: displayTimer, recording, start, toggle, stopAndRecord, discard, backfill }}>
      {children}
    </CourseTimerContext.Provider>
  )
}

export function useCourseTimer() {
  const ctx = useContext(CourseTimerContext)
  if (!ctx) throw new Error('useCourseTimer 必须在 CourseTimerProvider 内使用')
  return ctx
}
