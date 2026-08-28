import type { AgentJob, PlanTask, StrategyGenerationSession } from '../../types'

export const HEARTBEAT_DELAY_MS = 90_000
export const HEARTBEAT_STALE_MS = 180_000

export function parseServerTime(value?: string | null) {
  const parsed = value ? Date.parse(value) : Number.NaN
  return Number.isFinite(parsed) ? parsed : null
}

export function formatDuration(milliseconds: number) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  if (minutes < 60) return `${minutes} 分 ${rest} 秒`
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`
}

export function formatRelativeTime(value: string | null | undefined, nowMs: number) {
  const timestamp = parseServerTime(value)
  if (timestamp === null) return '暂无'
  return `${formatDuration(nowMs - timestamp)}前`
}

export function generationStage(job: AgentJob) {
  const progress = job.progress
  const currentCall = job.modelUsage?.currentCall
  return {
    stage: progress?.stage || currentCall?.stage || '',
    taskId: progress?.taskId || currentCall?.taskId || '',
    attempt: progress?.stageAttempt || currentCall?.attempt || 1,
    updatedAt: progress?.updatedAt || currentCall?.startedAt || job.updatedAt,
  }
}

export function generationHeadline(session: StrategyGenerationSession, tasks: PlanTask[]) {
  const { job } = session
  if (job.status === 'failed') return '复习主线真实生成失败'
  if (job.status === 'cancelled') return '服务端已登记停止；当前模型调用可能仍在收尾'
  if (job.status === 'completed') {
    // completed 只代表 handler 正常返回；result.partial=true 表示本批有课程未生成，
    // 必须如实提示，不得用"生成完成"掩盖部分失败（课程卡片会仍显示"内容生成中"）。
    const result = job.result as { partial?: boolean; pendingLessonCount?: number } | null
    if (result?.partial) {
      const pending = typeof result.pendingLessonCount === 'number' ? result.pendingLessonCount : ''
      return `本批生成结束，但仍有 ${pending ? `${pending} 节` : '部分'}课程未完成，可再次生成补齐`
    }
    return '本批课程生成完成'
  }
  if (session.stopRequested) return '已提交停止请求，等待当前调用结束'
  if (session.syncStatus === 'offline') return '状态同步中断，保留后台最后可信状态'
  if (session.syncStatus === 'degraded') return '状态同步波动，后台最后状态仍在运行'
  if (job.status === 'queued') return '等待后台 worker 接手'
  const stage = generationStage(job)
  const title = tasks.find((task) => task.id === stage.taskId)?.title
  const target = title ? `“${title}”` : '当前课程'
  if (stage.stage === 'preparing') return '正在读取课程资料'
  if (stage.stage === 'content_planning') return stage.attempt > 1 ? '正在修复课程内容规划' : '正在规划课程结构'
  if (stage.stage === 'lesson_guide') return stage.attempt > 1 ? `正在第 ${stage.attempt} 次修复 ${target} 讲义` : `正在生成 ${target} 讲义`
  if (stage.stage === 'lesson_questions') return stage.attempt > 1 ? `正在第 ${stage.attempt} 次补正 ${target} 自测` : `正在生成 ${target} 自测`
  if (stage.stage === 'mock_exam') return stage.attempt > 1 ? '正在修复课程模拟卷' : '正在生成课程模拟卷'
  if (stage.stage === 'finalizing') return '正在校验并保存本批课程'
  return '复习主线正在后台处理'
}

export function heartbeatHealth(job: AgentJob, nowMs: number) {
  const updatedAt = parseServerTime(job.updatedAt)
  if (job.status === 'queued') return { level: 'queued', label: '排队中' }
  if (job.status === 'cancelled') return { level: 'cancelled', label: '停止已登记' }
  if (job.status !== 'running' || updatedAt === null) return { level: job.status, label: '任务已结束' }
  const age = nowMs - updatedAt
  if (age < HEARTBEAT_DELAY_MS) return { level: 'healthy', label: '后台心跳正常' }
  if (age < HEARTBEAT_STALE_MS) return { level: 'delayed', label: '最近心跳延迟' }
  return { level: 'stale', label: '长时间无心跳，建议刷新' }
}

export function classifyGenerationError(error: string) {
  const text = error.toLowerCase()
  if (/quota|balance|余额|额度|insufficient/.test(text)) return '请检查模型账户余额或额度。'
  if (/api.?key|unauthorized|401|鉴权|密钥/.test(text)) return '请检查模型 API 密钥与服务地址。'
  if (/timeout|timed out|超时/.test(text)) return '上游模型请求超时，可检查网络和模型服务状态后重试。'
  return '可复制错误详情，检查模型配置后重试当前课程。'
}
