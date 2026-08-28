import { CheckCircle2, CircleAlert, RefreshCw, Square } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { PlanTask, StrategyGenerationSession } from '../types'
import { classifyGenerationError, formatDuration, formatRelativeTime, generationHeadline, generationStage, heartbeatHealth, parseServerTime } from '../features/courseGeneration/generationStatus'

type Props = {
  session: StrategyGenerationSession | null
  tasks: PlanTask[]
  completedCount: number
  totalCount: number
  isRefreshing: boolean
  actionError?: string
  onRefresh: () => void
  onStop: () => void
}

export function CourseGenerationStatusCard({ session, tasks, completedCount, totalCount, isRefreshing, actionError, onRefresh, onStop }: Props) {
  const [nowMs, setNowMs] = useState(Date.now())
  const active = Boolean(session && ['queued', 'running'].includes(session.job.status))
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [active])
  if (!session) return null
  const { job } = session
  const usage = job.modelUsage
  const stage = generationStage(job)
  const health = heartbeatHealth(job, nowMs)
  const createdAt = parseServerTime(job.createdAt) ?? nowMs
  const terminalAt = active ? nowMs : parseServerTime(job.updatedAt) ?? nowMs
  const stageStartedAt = parseServerTime(stage.updatedAt)
  return (
    <section className={`course-generation-card is-${job.status} sync-${session.syncStatus}`}>
      <div className={`course-generation-card-icon health-${health.level}`}>
        {job.status === 'completed' ? <CheckCircle2 size={21} /> : <RefreshCw className={active ? 'is-spinning' : ''} size={21} />}
      </div>
      <div className="course-generation-card-body">
        <strong>{generationHeadline(session, tasks)}</strong>
        <div className="course-generation-metrics">
          <span>课程 {completedCount}/{totalCount}</span>
          <span>总耗时 {formatDuration(terminalAt - createdAt)}</span>
          {active && stageStartedAt !== null && <span>当前阶段 {formatDuration(nowMs - stageStartedAt)}</span>}
          <span>{health.label}</span>
          <span>心跳 {formatRelativeTime(job.updatedAt, nowMs)}</span>
          <span>同步 {formatRelativeTime(session.lastSyncedAt, nowMs)}</span>
          <span>任务执行 {job.attempts}/{job.maxAttempts}</span>
          {usage && <span>模型调用成功 {usage.calls} / 失败 {usage.failures}</span>}
          {usage && <span>tokens {usage.totalTokens.toLocaleString()}</span>}
          {usage?.currentCall?.model && <span>当前模型 {usage.currentCall.model}</span>}
        </div>
        {session.source === 'recovered' && <p className="course-generation-note">已从服务端恢复此任务，计时来自服务端创建时间。</p>}
        {session.stopRequested && <p className="course-generation-warning">停止请求已登记；当前模型调用可能需要返回后才能完全停止，已完成小节会保留。</p>}
        {session.syncError && <p className="course-generation-warning" role="status">{session.syncError}（未将任务伪造为失败）</p>}
        {session.workspaceRefreshError && <p className="course-generation-warning" role="status">内容预览：{session.workspaceRefreshError}</p>}
        {job.status === 'failed' && <p className="course-generation-error" role="alert">{job.error || '服务端未提供错误详情'}<br />{classifyGenerationError(job.error || '')}</p>}
        {actionError && <p className="course-generation-error" role="alert">{actionError}</p>}
      </div>
      <div className="course-generation-actions">
        <button className="secondary-button" type="button" disabled={isRefreshing} onClick={onRefresh}>
          <RefreshCw className={isRefreshing ? 'is-spinning' : ''} size={16} /> {isRefreshing ? '刷新中' : session.syncStatus === 'offline' ? '重新连接' : '刷新状态'}
        </button>
        {active && <button className="primary-button" type="button" disabled={session.stopRequested} onClick={onStop}>
          <Square size={16} /> {session.stopRequested ? '停止请求中' : '请求停止'}
        </button>}
        {job.status === 'failed' && <span className="course-generation-failed-badge"><CircleAlert size={15} /> 服务端确认失败</span>}
      </div>
    </section>
  )
}
