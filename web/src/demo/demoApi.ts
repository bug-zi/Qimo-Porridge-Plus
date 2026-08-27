/**
 * 演示模式的 API 实现：与 ../api.ts 完全同签名（经 ApiSurface 类型约束），
 * 数据来自 web/public/demo/snapshot.json（后端快照，导出时已清洗敏感信息），
 * 全部状态保存在内存 store 中——刷新页面即重置，适合公开演示。
 *
 * 与真实后端的行为对齐点（详见各函数注释）：
 * - dailyProgress 按访问当天用后端同款公式重算（study_service.build_daily_progress）；
 * - 考试日期在加载时整体平移到未来，保证演示永远处于"考前"状态；
 * - agent 流式对话按 SSE 事件合同回调（token/step/tool_start/tool_end/done），
 *   done 的 workspace 中追加本轮 user/assistant 消息（对齐 study_service.py 行为）。
 */
import type {
  AccountProfile,
  AdjustmentProposal,
  AgentJob,
  ArchiveItem,
  Course,
  CourseMindMap,
  DailyProgress,
  EmbeddingProfile,
  ExternalSource,
  GlossaryResponse,
  KnowledgeBaseStatus,
  MaterialPreview,
  McpServer,
  MockSubmitResult,
  ModelProfile,
  PlanParamsAdjustRequest,
  PlanParamsAdjustResponse,
  PlanTask,
  PracticeAnswerResult,
  SearchResult,
  StrategyDocuments,
  StrategyRevisionMessage,
  StudyMessage,
  StudyWorkspace,
  TimeLogEntry,
  UserProfilePrompt,
} from '../types'
import { fillScriptPlaceholders, matchAgentScript } from './scripts'
import * as localApi from '../api'

/* ------------------------------------------------------------------ */
/* 内部类型：api.ts 的私有响应类型在此声明结构等价版本（快照即后端原样 JSON） */

type RuntimeModel = {
  baseUrl: string
  model: string
  connected: boolean
  hasApiKey?: boolean
  availableModels?: string[]
}

type CourseApiResponse = {
  id: string
  name: string
  exam_date: string
  target_score: number
  daily_hours: number
  progress: number
}

type ArchiveItemApiResponse = {
  id: string
  item_type: ArchiveItem['itemType']
  entity_id: string
  title: string
  course_id?: string | null
  course_name?: string | null
  deleted_at: string
  purge_after: string
}

type CourseMindMapApiResponse = {
  status: 'ready' | 'empty'
  courseId: string
  mindMap: CourseMindMap | null
}

/** 快照中的 glossary 响应（后端原标 JSON：camelCase term + snake_case 字段，api.ts toGlossaryTerm 负责转换） */
type GlossaryApiResponse = {
  courseId: string
  terms: localApi.GlossaryTermApiResponse[]
  status: Partial<localApi.GlossaryStatusApiResponse>
}

type ApiSurface = typeof import('../api')

/* ------------------------------------------------------------------ */
/* 快照结构（backend/scripts/export_demo_snapshot.py 产出） */

type DemoSnapshot = {
  exportedAt: string
  courses: CourseApiResponse[]
  workspaces: Record<string, StudyWorkspace>
  mindMaps: Record<string, CourseMindMapApiResponse>
  strategyDocuments: Record<string, StrategyDocuments>
  knowledgeStatus: Record<string, KnowledgeBaseStatus>
  materialPreviews: Record<string, Record<string, MaterialPreview>>
  glossaries?: Record<string, GlossaryApiResponse>
  archive: ArchiveItemApiResponse[]
  runtimeModel: RuntimeModel
  userProfile: UserProfilePrompt
  accountProfile?: AccountProfile
  embeddingProfile: EmbeddingProfile
  mcpServers: McpServer[]
}

/* ------------------------------------------------------------------ */
/* 内存 store */

let snapshot: DemoSnapshot | null = null
let snapshotPromise: Promise<DemoSnapshot> | null = null

function loadSnapshot(): Promise<DemoSnapshot> {
  if (snapshot) return Promise.resolve(snapshot)
  if (snapshotPromise) return snapshotPromise
  snapshotPromise = fetch('/demo/snapshot.json')
    .then((response) => {
      if (!response.ok) throw new Error('演示数据快照加载失败')
      return response.json() as Promise<DemoSnapshot>
    })
    .then((data) => {
      snapshot = normalizeSnapshot(data)
      return snapshot
    })
  return snapshotPromise
}

/** 让每门课的"考试日期"永远在未来：以最早考试日为锚点，把整体平移到访问日之后。 */
function normalizeSnapshot(data: DemoSnapshot): DemoSnapshot {
  const anchor = data.courses.reduce<string | null>((earliest, course) => {
    const examDate = course.exam_date
    return !earliest || examDate < earliest ? examDate : earliest
  }, null)
  if (!anchor) return data

  const today = new Date()
  const anchorDate = new Date(`${anchor}T00:00:00`)
  const daysToShift = Math.max(0, Math.ceil((today.getTime() - anchorDate.getTime()) / 86_400_000) + 3)
  if (daysToShift === 0) return data

  const shift = (isoDate: string) => {
    if (!isoDate) return isoDate
    const date = new Date(`${isoDate.slice(0, 10)}T00:00:00`)
    if (Number.isNaN(date.getTime())) return isoDate
    date.setDate(date.getDate() + daysToShift)
    return date.toISOString().slice(0, 10)
  }

  data.courses = data.courses.map((course) => ({ ...course, exam_date: shift(course.exam_date) }))
  for (const courseId of Object.keys(data.workspaces)) {
    const workspace = data.workspaces[courseId]
    workspace.course = { ...workspace.course, examDate: shift(workspace.course.examDate) }
    if (workspace.planStartDate) workspace.planStartDate = shift(workspace.planStartDate)
    if (workspace.onboarding) workspace.onboarding = { ...workspace.onboarding, examDate: shift(workspace.onboarding.examDate) }
    if (workspace.tasks) {
      workspace.tasks = workspace.tasks.map((task) => ({ ...task, courseId }))
    }
  }
  return data
}

function requireSnapshot(): DemoSnapshot {
  if (!snapshot) throw new Error('演示数据尚未加载')
  return snapshot
}

function workspaceOf(courseId: string): StudyWorkspace {
  const workspace = requireSnapshot().workspaces[courseId]
  if (!workspace) throw new Error('演示课程不存在')
  return workspace
}

/* 日期工具（后端 build_daily_progress 的 TS 复刻） */

function toIsoDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function buildDailyProgress(workspace: StudyWorkspace, today = new Date()): DailyProgress {
  const tasks = workspace.tasks ?? []
  const maxDay = tasks.reduce((max, task) => Math.max(max, task.day ?? 0), 1)
  let todayDay = 1
  if (workspace.planStartDate) {
    const startDate = new Date(`${workspace.planStartDate.slice(0, 10)}T00:00:00`)
    if (!Number.isNaN(startDate.getTime())) {
      todayDay = Math.max(1, Math.min(maxDay, Math.floor((today.getTime() - startDate.getTime()) / 86_400_000) + 1))
    }
  }
  const todayIso = toIsoDate(today)
  const plannedToday = tasks
    .filter((task) => (task.day ?? 0) === todayDay)
    .reduce((sum, task) => sum + task.duration, 0)
  const spentToday = (workspace.timeLog ?? [])
    .filter((entry) => entry.date === todayIso)
    .reduce((sum, entry) => sum + entry.minutes, 0)
  const overdue = tasks
    .filter((task) => (task.day ?? 0) < todayDay && task.status !== 'completed')
    .map((task) => ({
      id: task.id,
      title: task.title,
      day: task.day ?? 0,
      duration: task.duration,
      priority: task.priority,
      status: task.status,
    }))
  return {
    date: todayIso,
    todayDay,
    maxDay,
    plannedToday,
    spentToday,
    remaining: Math.max(0, plannedToday - spentToday),
    overBudget: plannedToday > 0 && spentToday > plannedToday,
    overdue,
  }
}

/** 每次返回 workspace 前重算 dailyProgress，保证演示日期新鲜。 */
function withFreshProgress(workspace: StudyWorkspace): StudyWorkspace {
  return { ...workspace, dailyProgress: buildDailyProgress(workspace) }
}

function inferCourseIcon(name: string): Course['icon'] {
  const normalizedName = name.toLowerCase()
  if (name.includes('英语') || normalizedName.includes('english')) return 'english'
  if (name.includes('物理') || normalizedName.includes('physics')) return 'physics'
  if (name.includes('数据库') || normalizedName.includes('database')) return 'database'
  if (name.includes('数据结构') || name.includes('程序') || normalizedName.includes('code')) return 'code'
  if (name.includes('数学') || name.includes('概率') || name.includes('经济') || normalizedName.includes('math')) return 'math'
  return 'system'
}

function resolveCourseColor(courseId: string) {
  const palette = ['#ff537f', '#3973e8', '#16a7a5', '#ff8a3d', '#a94cc6', '#2f65d8']
  const hash = Array.from(courseId).reduce((sum, char) => sum + char.charCodeAt(0), 0)
  return palette[hash % palette.length]
}

function toCourse(course: CourseApiResponse): Course {
  return {
    id: course.id,
    name: course.name,
    examDate: course.exam_date,
    targetScore: course.target_score,
    dailyHours: course.daily_hours,
    progress: course.progress,
    color: resolveCourseColor(course.id),
    icon: inferCourseIcon(course.name),
  }
}

function toArchiveItem(item: ArchiveItemApiResponse): ArchiveItem {
  return {
    id: item.id,
    itemType: item.item_type,
    entityId: item.entity_id,
    title: item.title,
    courseId: item.course_id ?? undefined,
    courseName: item.course_name ?? undefined,
    deletedAt: item.deleted_at,
    purgeAfter: item.purge_after,
  }
}

/** 深拷贝 + dailyProgress 重算 + course 装饰字段补全。 */
function decoratedWorkspace(courseId: string): StudyWorkspace {
  const raw = JSON.parse(JSON.stringify(workspaceOf(courseId))) as StudyWorkspace
  raw.course = {
    ...raw.course,
    color: raw.course.color || resolveCourseColor(raw.course.id),
    icon: raw.course.icon || inferCourseIcon(raw.course.name),
  }
  return withFreshProgress(raw)
}

function nowIso(): string {
  return new Date().toISOString().slice(0, 19)
}

function daysUntil(examDate: string): number {
  const exam = new Date(`${examDate.slice(0, 10)}T00:00:00`)
  if (Number.isNaN(exam.getTime())) return 0
  const today = new Date()
  return Math.ceil((exam.getTime() - new Date(toIsoDate(today)).getTime()) / 86_400_000)
}

/* ------------------------------------------------------------------ */
/* 变更辅助 */

function replaceWorkspace(courseId: string, workspace: StudyWorkspace): StudyWorkspace {
  requireSnapshot().workspaces[courseId] = JSON.parse(JSON.stringify(workspace)) as StudyWorkspace
  return decoratedWorkspace(courseId)
}

function replaceFirstText(node: unknown, originalText: string, rewrittenText: string): boolean {
  if (Array.isArray(node)) {
    for (let index = 0; index < node.length; index += 1) {
      const value = node[index]
      if (typeof value === 'string' && value.includes(originalText)) {
        node[index] = value.replace(originalText, rewrittenText)
        return true
      }
      if (value && typeof value === 'object' && replaceFirstText(value, originalText, rewrittenText)) return true
    }
    return false
  }
  if (node && typeof node === 'object') {
    for (const [key, value] of Object.entries(node)) {
      if (typeof value === 'string' && value.includes(originalText)) {
        ;(node as Record<string, unknown>)[key] = value.replace(originalText, rewrittenText)
        return true
      }
      if (value && typeof value === 'object' && replaceFirstText(value, originalText, rewrittenText)) return true
    }
  }
  return false
}

function recomputeCourseProgress(workspace: StudyWorkspace): number {
  if (!workspace.tasks.length) return workspace.course.progress
  return Math.round(workspace.tasks.reduce((sum, task) => sum + task.progress, 0) / workspace.tasks.length)
}

function bumpMastery(workspace: StudyWorkspace, knowledgePointId: string, delta: number): void {
  const point = workspace.knowledgePoints.find((kp) => kp.id === knowledgePointId)
  if (!point) return
  point.mastery = Math.max(0, Math.min(100, point.mastery + delta))
}

function appendMessages(workspace: StudyWorkspace, userMessage: string, reply: string, mode: 'chat' | 'agent'): void {
  const stamp = Date.now()
  const messages: StudyMessage[] = [
    { id: `user-${stamp}`, role: 'user', mode, content: userMessage, createdAt: '刚刚' },
    { id: `assistant-${stamp + 1}`, role: 'assistant', mode, content: reply, createdAt: '刚刚' },
  ]
  workspace.messages = [...(workspace.messages ?? []), ...messages]
}

function scriptStats(workspace: StudyWorkspace) {
  const progress = workspace.tasks.length
    ? Math.round(workspace.tasks.reduce((sum, task) => sum + task.progress, 0) / workspace.tasks.length)
    : workspace.course.progress
  const mastery = workspace.knowledgePoints.length
    ? Math.round(workspace.knowledgePoints.reduce((sum, kp) => sum + kp.mastery, 0) / workspace.knowledgePoints.length)
    : 50
  const daily = workspace.dailyProgress ?? buildDailyProgress(workspace)
  return {
    course: workspace.course.name,
    progress,
    daysLeft: daysUntil(workspace.course.examDate),
    mastery,
    todayDay: daily.todayDay,
    maxDay: daily.maxDay,
    plannedToday: daily.plannedToday,
    spentToday: daily.spentToday,
    remaining: daily.remaining,
    overdueCount: daily.overdue.length,
  }
}

/* ------------------------------------------------------------------ */
/* 任务进度联动（对齐后端：完成任务时推进对应知识点掌握度与课程进度） */

function applyTaskStatusSideEffects(workspace: StudyWorkspace, taskId: string, nextStatus: PlanTask['status']): void {
  const task = workspace.tasks.find((item) => item.id === taskId)
  if (!task) return
  const wasCompleted = task.status === 'completed'
  task.status = nextStatus
  task.progress = nextStatus === 'completed' ? 100 : nextStatus === 'in-progress' ? Math.max(task.progress, 5) : 0
  if (task.knowledgePointId) {
    if (nextStatus === 'completed' && !wasCompleted) bumpMastery(workspace, task.knowledgePointId, 10)
    if (nextStatus !== 'completed' && wasCompleted) bumpMastery(workspace, task.knowledgePointId, -10)
  }
  workspace.course.progress = recomputeCourseProgress(workspace)
}

/* ------------------------------------------------------------------ */
/* demoApi 实现 */

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

const demoApi: ApiSurface = {
  /* 演示模式无后端；apiBaseUrl 仅满足与 ../api.ts 同签名的类型约束 */
  apiBaseUrl: '',

  /* ---------------- 课程 ---------------- */

  async listCourses() {
    const data = await loadSnapshot()
    return data.courses.map(toCourse)
  },

  async createCourse(payload) {
    const data = await loadSnapshot()
    const courseId = `course-demo-${Date.now()}`
    const course: CourseApiResponse = {
      id: courseId,
      name: payload.name,
      exam_date: payload.examDate,
      target_score: payload.targetScore,
      daily_hours: payload.dailyHours,
      progress: 0,
    }
    data.courses.push(course)
    // 新课程即时产出兜底 workspace（对齐 App.createLocalCourseWorkspace 的结构）
    data.workspaces[courseId] = {
      course: toCourse(course),
      assessmentProfile: {
        summary: `${payload.name}课程已创建（演示）。`,
        questionTypes: ['待整理'],
      },
      diagnostic: { estimatedScore: '未摸底', message: '演示模式下暂不支持完整的初始化流程。' },
      knowledgePoints: [],
      tasks: [],
      practiceQuestions: [],
      mockQuestions: [],
      materials: [],
      wrongAnswers: [],
      note: `## ${payload.name}考前笔记\n\n- 演示模式下新课程仅展示框架。`,
      messages: [
        {
          id: `${courseId}-welcome`,
          role: 'assistant',
          content: `${payload.name}课程已加入（演示模式）。完整版会在此时导入资料、摸底并生成复习主线。`,
          createdAt: '刚刚',
        },
      ],
      generatedAt: nowIso(),
      generationMode: 'fallback',
    }
    return toCourse(course)
  },

  async deleteCourse(courseId) {
    const data = await loadSnapshot()
    const index = data.courses.findIndex((course) => course.id === courseId)
    if (index === -1) throw new Error('课程不存在')
    const [removed] = data.courses.splice(index, 1)
    delete data.workspaces[courseId]
    delete data.mindMaps[courseId]
    delete data.strategyDocuments[courseId]
    delete data.knowledgeStatus[courseId]
    delete data.materialPreviews[courseId]
    const archiveItem: ArchiveItemApiResponse = {
      id: `archive-demo-${Date.now()}`,
      item_type: 'course',
      entity_id: removed.id,
      title: removed.name,
      course_id: removed.id,
      course_name: removed.name,
      deleted_at: nowIso(),
      purge_after: new Date(Date.now() + 7 * 86_400_000).toISOString(),
    }
    data.archive.push(archiveItem)
    return toArchiveItem(archiveItem)
  },

  async getCourseWorkspace(courseId) {
    await loadSnapshot()
    return decoratedWorkspace(courseId)
  },

  async getCourseMindMap(courseId) {
    const data = await loadSnapshot()
    return data.mindMaps[courseId] ?? { status: 'empty', courseId, mindMap: null }
  },

  async generateCourseMindMap(courseId) {
    await delay(1200)
    const data = await loadSnapshot()
    return data.mindMaps[courseId] ?? { status: 'empty', courseId, mindMap: null }
  },

  async regroupCourseMindMapModules(courseId) {
    await delay(600)
    const data = await loadSnapshot()
    return data.mindMaps[courseId] ?? { status: 'empty', courseId, mindMap: null }
  },

  async saveCourseMindMap(courseId, mindMap) {
    const data = await loadSnapshot()
    const current = data.mindMaps[courseId] ?? { status: 'ready' as const, courseId, mindMap: null }
    data.mindMaps[courseId] = { ...current, mindMap }
    return data.mindMaps[courseId]
  },

  /* ---------------- 搜索（复刻 main.py search_course 的 AND 匹配） ---------------- */

  async searchCourse(courseId, query) {
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean)
    if (!terms.length) return []
    const matches = (...values: unknown[]) => {
      const text = values.filter((value) => value != null).join(' ').toLowerCase()
      return terms.every((term) => text.includes(term))
    }
    const results: SearchResult[] = []
    const seen = new Set<string>()
    const addResult = (
      id: string,
      type: SearchResult['type'],
      module: SearchResult['module'],
      title: string,
      excerpt: string,
      source = '',
    ) => {
      if (seen.has(id) || results.length >= 30) return
      seen.add(id)
      results.push({ id, type, module, title, excerpt: excerpt.trim().slice(0, 240), source })
    }

    for (const material of workspace.materials) {
      if (matches(material.name, material.detail)) {
        addResult(`material-${material.relativePath}`, 'material', 'materials', material.name, material.detail)
      }
    }
    for (const point of workspace.knowledgePoints) {
      if (matches(point.name, point.summary, point.source)) {
        addResult(`knowledge-${point.id}`, 'knowledge', 'overview', point.name, point.summary, point.source)
      }
    }
    if (matches(workspace.note)) {
      addResult('course-note', 'note', 'notes', '课程复习笔记', workspace.note)
    }
    for (const wrongAnswer of workspace.wrongAnswers) {
      if (matches(wrongAnswer.title, wrongAnswer.tag, wrongAnswer.mistakeType, wrongAnswer.source)) {
        addResult(`wrong-answer-${wrongAnswer.id}`, 'wrong-answer', 'errors', wrongAnswer.title, wrongAnswer.mistakeType, wrongAnswer.source ?? wrongAnswer.tag)
      }
    }
    const questionGroups: Array<[PlanTask[] | undefined, Array<{ id: string; prompt: string; explanation: string; source?: string; options: string[] }>, SearchResult['module']]> = [
      [undefined, workspace.practiceQuestions, 'practice'],
      [undefined, workspace.mockQuestions, 'mock'],
      [undefined, workspace.diagnosticQuestions ?? [], 'overview'],
    ]
    for (const [, questions, module] of questionGroups) {
      for (const question of questions) {
        if (matches(question.prompt, question.explanation, question.source, ...question.options)) {
          addResult(`question-${question.id}`, 'question', module, question.prompt, question.explanation, question.source ?? '')
        }
      }
    }
    return results
  },

  /* ---------------- 设置 / 摸底 / 策略文档 ---------------- */

  async saveCourseSetup(courseId, payload) {
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    workspace.course = { ...workspace.course, name: payload.courseName, examDate: payload.examDate, targetScore: payload.targetScore, dailyHours: payload.dailyHours }
    workspace.onboarding = workspace.onboarding
      ? { ...workspace.onboarding, ...payload }
      : undefined
    return replaceWorkspace(courseId, workspace)
  },

  async reviewCourseReadability(courseId) {
    await delay(450)
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    const ready = workspace.tasks.filter((task) => task.kind !== 'orientation' && task.studyGuide)
    const pending = workspace.tasks.filter((task) => task.kind !== 'orientation' && !task.studyGuide).length
    for (const task of ready) {
      if (task.studyGuide) task.studyGuide.readabilityReview = { version: 1, status: 'passed', score: 94, issues: [], summary: '排版清晰，可直接阅读', taskId: task.id }
    }
    workspace.readabilityReview = { version: 1, status: pending ? 'attention' : 'passed', score: ready.length ? 94 : 0, reviewedAt: nowIso(), reviewedLessonCount: ready.length, passedLessonCount: ready.length, attentionLessonCount: 0, pendingLessonCount: pending, summary: pending ? `0 课需要关注，${pending} 课待生成` : '全部课程排版清晰', lessons: ready.map((task) => ({ taskId: task.id, status: 'passed' as const, score: 94, issueCount: 0 })) }
    return replaceWorkspace(courseId, workspace)
  },

  async submitCourseDiagnostic(courseId, answers) {
    await delay(800)
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    if (workspace.diagnosticQuestions?.length) {
      let score = 0
      let total = 0
      for (const question of workspace.diagnosticQuestions) {
        total += 1
        if (answers[question.id] === question.answerIndex) score += 1
      }
      if (workspace.onboarding) {
        workspace.onboarding.diagnosticScore = score
        workspace.onboarding.diagnosticTotal = total
        workspace.onboarding.diagnosticPercent = total ? Math.round((score / total) * 100) : 0
      }
      workspace.diagnostic = {
        estimatedScore: `${Math.round((score / Math.max(1, total)) * 100)} 分`,
        message: '演示模式：已根据摸底结果更新预估。',
      }
    }
    return replaceWorkspace(courseId, workspace)
  },

  async getStrategyDocuments(courseId) {
    const data = await loadSnapshot()
    return data.strategyDocuments[courseId]
  },

  async generateStrategyDocuments(courseId) {
    await delay(1500)
    const data = await loadSnapshot()
    return data.strategyDocuments[courseId]
  },

  async saveStrategyDocuments(courseId, payload) {
    const data = await loadSnapshot()
    const current = data.strategyDocuments[courseId]
    if (current) {
      data.strategyDocuments[courseId] = {
        ...current,
        reviewPlan: { ...current.reviewPlan, content: payload.reviewPlan, version: payload.reviewPlanVersion, updatedBy: 'user', updatedAt: nowIso() },
        coursePrompt: { ...current.coursePrompt, content: payload.coursePrompt, version: payload.coursePromptVersion, updatedBy: 'user', updatedAt: nowIso() },
      }
    }
    return data.strategyDocuments[courseId]
  },

  async approveStrategyDocuments(courseId) {
    await delay(1000)
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    if (workspace.strategyDocuments) workspace.strategyDocuments.status = 'approved'
    if (workspace.onboarding) workspace.onboarding.status = 'planned'
    return replaceWorkspace(courseId, workspace)
  },

  async approveStrategyDocumentsInBackground(courseId) {
    await loadSnapshot()
    return { jobId: registerJob(courseId), courseId }
  },

  async getAgentJob(jobId) {
    return getJob(jobId)
  },

  async cancelAgentJob(jobId) {
    const job = getJob(jobId)
    return { ...job, status: 'cancelled' as const, updatedAt: nowIso() }
  },

  /* ---------------- 术语词条 ---------------- */

  async getCourseGlossary(courseId) {
    const data = await loadSnapshot()
    return toGlossaryResponse(courseId, data.glossaries?.[courseId])
  },

  async getCourseGlossaryStatus(courseId) {
    const data = await loadSnapshot()
    return toGlossaryResponse(courseId, data.glossaries?.[courseId]).status
  },

  async refreshCourseGlossary(courseId) {
    await loadSnapshot()
    return { jobId: registerJob(courseId, 'glossary_refresh'), courseId }
  },

  async updateGlossaryTerm(courseId, termId, fields) {
    const data = await loadSnapshot()
    const entry = mutableGlossaryEntry(data, courseId)
    const target = entry.terms.find((item) => item.id === termId)
    if (!target) throw new Error('词条不存在')
    if (fields.term !== undefined) target.term = fields.term
    if (fields.aliases !== undefined) target.aliases = fields.aliases
    if (fields.oneLiner !== undefined) target.oneLiner = fields.oneLiner
    if (fields.article !== undefined) target.article = fields.article
    if (fields.examTips !== undefined) target.examTips = fields.examTips
    if (fields.pitfalls !== undefined) target.pitfalls = fields.pitfalls
    if (fields.importance !== undefined) target.importance = fields.importance
    if (fields.status !== undefined) target.status = fields.status
    target.updatedAt = nowIso()
    return localApi.toGlossaryTerm(target)
  },

  async deleteGlossaryTerm(courseId, termId) {
    const data = await loadSnapshot()
    const entry = mutableGlossaryEntry(data, courseId)
    entry.terms = entry.terms.filter((item) => item.id !== termId)
    return toGlossaryResponse(courseId, entry)
  },

  async saveCoursePrompt(courseId, coursePrompt, version) {
    const data = await loadSnapshot()
    const current = data.strategyDocuments[courseId]
    if (current) {
      data.strategyDocuments[courseId] = {
        ...current,
        coursePrompt: { ...current.coursePrompt, content: coursePrompt, version, updatedBy: 'user', updatedAt: nowIso() },
      }
    }
    return data.strategyDocuments[courseId]
  },

  /* ---------------- 材料 ---------------- */

  async getCourseMaterialPreview(courseId, relativePath) {
    const data = await loadSnapshot()
    const preview = data.materialPreviews[courseId]?.[relativePath]
    if (!preview) throw new Error('演示模式下该材料不可预览。')
    return preview
  },

  getCourseMaterialFileUrl() {
    return '#'
  },

  getCourseMaterialConvertedFileUrl() {
    return '#'
  },

  async rescanCourseMaterials(courseId) {
    await delay(600)
    await loadSnapshot()
    return decoratedWorkspace(courseId)
  },

  async uploadCourseMaterials(courseId, files, role = 'supplementary') {
    await delay(900)
    const fileArray = Array.from(files)
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    for (const file of fileArray) {
      workspace.materials.push({
        name: file.name,
        relativePath: file.name,
        type: (file.name.split('.').pop() ?? 'FILE').toUpperCase(),
        size: file.size,
        detail: `${file.type || 'application/octet-stream'} · ${(file.size / 1024).toFixed(1)} KB · 演示模式占位`,
        role: role === 'primary' ? 'primary' : 'supplementary',
        isPrimary: role === 'primary',
        priorityOrder: workspace.materials.length + 1,
        previewStatus: 'unsupported',
        previewLabel: '演示模式',
        previewMessage: '演示站不保存上传的文件，仅展示导入流程。',
      })
    }
    return replaceWorkspace(courseId, workspace)
  },

  async updateCourseMaterialRole(courseId, relativePath, payload) {
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    workspace.materials = workspace.materials.map((material) => {
      if (material.relativePath !== relativePath) return material
      const role = payload.role === 'primary' ? 'primary' : 'supplementary'
      return { ...material, role, isPrimary: role === 'primary', priorityOrder: payload.priorityOrder ?? material.priorityOrder ?? 0 }
    })
    return replaceWorkspace(courseId, workspace)
  },

  async deleteCourseMaterial(courseId, relativePath) {
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    workspace.materials = workspace.materials.filter((material) => material.relativePath !== relativePath)
    return replaceWorkspace(courseId, workspace)
  },

  /* ---------------- 模型 / 画像 / 知识库 ---------------- */

  async getRuntimeModel() {
    const data = await loadSnapshot()
    return data.runtimeModel
  },

  async saveRuntimeModel(payload) {
    const data = await loadSnapshot()
    data.runtimeModel = { ...data.runtimeModel, baseUrl: payload.baseUrl, model: payload.model, connected: true, hasApiKey: payload.apiKey.length > 0 }
    return data.runtimeModel
  },

  async getAccountProfile() {
    const data = await loadSnapshot()
    data.accountProfile ??= {
      id: 'demo',
      email: 'demo@example.com',
      displayName: '演示用户',
      role: 'user',
      avatarUrl: '',
      gender: '',
      age: null,
      signature: '',
    }
    return data.accountProfile
  },

  async saveAccountProfile(payload) {
    const data = await loadSnapshot()
    const current = await demoApi.getAccountProfile()
    data.accountProfile = { ...current, ...payload }
    return data.accountProfile
  },

  async uploadAccountAvatar(file: File) {
    const data = await loadSnapshot()
    const current = await demoApi.getAccountProfile()
    const avatarUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result ?? ''))
      reader.onerror = () => reject(new Error('头像读取失败'))
      reader.readAsDataURL(file)
    })
    data.accountProfile = { ...current, avatarUrl }
    return data.accountProfile
  },

  async deleteAccountAvatar() {
    const data = await loadSnapshot()
    const current = await demoApi.getAccountProfile()
    data.accountProfile = { ...current, avatarUrl: '' }
    return data.accountProfile
  },

  async getUserProfilePrompt() {
    const data = await loadSnapshot()
    return data.userProfile
  },

  async saveUserProfilePrompt(content) {
    const data = await loadSnapshot()
    data.userProfile = { content, updatedAt: nowIso() }
    return data.userProfile
  },
  async submitCourseFeedback(_courseId, payload) {
    await delay(250)
    const feedbackId = `demo-feedback-${Date.now()}`
    return {
      feedbackId,
      status: 'analyzed',
      message: '演示模式：课程意见已记录，并已生成当前片段优化建议。',
      rewriteProposal: {
        feedbackId,
        originalText: payload.selectedText,
        rewrittenText: payload.selectedText + '\n\n（演示改写：这里会根据你的意见重新组织表达。）',
        rationale: '演示模式下返回示例改写。',
        safetyNotes: [],
        replaceable: Boolean(payload.context?.field),
        target: payload.context ?? {},
        createdAt: nowIso(),
      },
    }
  },

  async submitGlobalCourseFeedback(courseId, taskId, sectionId, sectionIndex, userComment) {
    await delay(300)
    await loadSnapshot()
    const task = decoratedWorkspace(courseId).tasks.find((item) => item.id === taskId)
    if (!task?.studyGuide) throw new Error('当前任务没有可修改的讲义内容')
    const feedbackId = `demo-global-feedback-${Date.now()}`
    const revisedSection = JSON.parse(JSON.stringify(task.studyGuide.sections?.[sectionIndex] ?? { id: sectionId, label: `第 ${sectionIndex + 1} 小节`, title: '当前小节' }))
    return {
      feedbackId, status: 'analyzed', message: '演示模式：小节意见已记录，并已生成当前小节修改预览。',
      proposal: {
        feedbackId, taskId, taskTitle: task.title, sectionId, sectionIndex, sectionLabel: revisedSection.label ?? `第 ${sectionIndex + 1} 小节`, changeSummary: `已按要求修改当前小节：${userComment}`,
        rationale: '演示小节修改流程。', revisedSection, baseRevision: 'demo', createdAt: nowIso(),
      },
    }
  },

  async applyGlobalCourseFeedback(courseId, feedbackId) {
    await delay(220)
    await loadSnapshot()
    return { feedbackId, message: '演示模式：已应用当前小节修改。', workspace: replaceWorkspace(courseId, decoratedWorkspace(courseId)) }
  },

  async refineCourseFeedbackRewrite(_courseId, feedbackId, extraComment, previousRewrite) {
    await delay(250)
    return {
      feedbackId,
      rewriteProposal: {
        feedbackId,
        originalText: '',
        rewrittenText: previousRewrite + '\n\n（演示继续修改：' + extraComment + '）',
        rationale: '演示模式下根据补充意见继续修改。',
        safetyNotes: [],
        replaceable: true,
        target: {},
        createdAt: nowIso(),
      },
    }
  },

  async applyCourseFeedbackRewrite(courseId, feedbackId, originalText, rewrittenText, target) {
    await delay(250)
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    const task = workspace.tasks.find((item) => item.id === target?.taskId)
    if (!task?.studyGuide || !replaceFirstText(task.studyGuide, originalText, rewrittenText)) {
      throw new Error('当前内容已经变化，找不到原始选中文本，请重新选择')
    }
    ;(task as PlanTask & { contentUpdatedAt?: string }).contentUpdatedAt = nowIso()
    return { feedbackId, message: '演示模式：已确认替换。', workspace: replaceWorkspace(courseId, workspace) }
  },

  async getCourseFeedbackRules(_courseId) {
    await delay(120)
    return { version: 1, rules: [], summaryPrompt: '', updatedAt: '' }
  },

  async getEmbeddingProfile() {
    const data = await loadSnapshot()
    return data.embeddingProfile
  },

  async saveEmbeddingProfile(payload) {
    const data = await loadSnapshot()
    data.embeddingProfile = { ...data.embeddingProfile, ...payload }
    return data.embeddingProfile
  },

  async testEmbeddingProfile() {
    await delay(800)
    const data = await loadSnapshot()
    return { ...data.embeddingProfile, success: true }
  },

  async rebuildKnowledgeEmbeddings(_courseId) {
    await delay(1200)
    const data = await loadSnapshot()
    return data.embeddingProfile
  },

  async getKnowledgeBaseStatus(courseId) {
    const data = await loadSnapshot()
    return data.knowledgeStatus[courseId] ?? {
      courseId,
      materials: 0,
      chunks: 0,
      chatTurns: 0,
      learningEvents: 0,
      memories: 0,
      embedding: data.embeddingProfile,
    }
  },

  /* ---------------- 作答 ---------------- */

  async submitCoursePracticeAnswer(courseId, questionId, answerIndex, mode) {
    await delay(500)
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    const question = workspace.practiceQuestions.find((item) => item.id === questionId)
    if (!question) throw new Error('题目不存在')
    const correct = question.answerIndex === answerIndex
    bumpMastery(workspace, question.knowledgePointId, correct ? 8 : -5)
    const mastery = workspace.knowledgePoints.find((kp) => kp.id === question.knowledgePointId)?.mastery ?? 50
    workspace.practiceAnswers = workspace.practiceAnswers ?? {}
    workspace.practiceAnswers[questionId] = {
      answerIndex,
      correct,
      explanation: question.explanation,
      mastery,
      answeredAt: nowIso(),
      mode: mode ?? '刷题练习',
    }
    if (!correct) {
      const existing = workspace.wrongAnswers.find((item) => item.questionId === questionId)
      if (existing) {
        existing.count += 1
        existing.isReviewed = false
      } else {
        workspace.wrongAnswers.push({
          id: `wrong-demo-${Date.now()}`,
          questionId,
          questionType: mode === '主线学习' ? '主线学习' : '刷题练习',
          source: question.source,
          title: question.prompt.slice(0, 60),
          tag: workspace.knowledgePoints.find((kp) => kp.id === question.knowledgePointId)?.name ?? '未分类',
          mistakeType: '概念混淆',
          count: 1,
          isReviewed: false,
        })
      }
    }
    return {
      correct,
      explanation: question.explanation,
      mastery,
      generatedSimilarCount: 0,
      workspace: replaceWorkspace(courseId, workspace),
    }
  },

  async submitCourseWrongAnswerRetry(courseId, wrongAnswerId, answerIndex) {
    const workspace0 = await demoApi.getCourseWorkspace(courseId)
    const wrongAnswer = workspace0.wrongAnswers.find((item) => item.id === wrongAnswerId)
    if (!wrongAnswer?.questionId) throw new Error('错题不存在')
    const result = await demoApi.submitCoursePracticeAnswer(courseId, wrongAnswer.questionId, answerIndex, '刷题练习')
    if (result.correct) {
      const workspace = result.workspace
      const target = workspace.wrongAnswers.find((item) => item.id === wrongAnswerId)
      if (target) {
        target.isReviewed = true
        target.reviewedAt = nowIso()
      }
      result.workspace = replaceWorkspace(courseId, workspace)
    }
    return result as PracticeAnswerResult
  },

  async repairCourseMockQuestions(courseId) {
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    return { workspace, repaired: false, source: 'existing' as const, warning: '', questionCount: workspace.mockQuestions.length }
  },

  async submitCourseMockAnswers(courseId, answers) {
    await delay(1200)
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    let score = 0
    let total = 0
    const results = workspace.mockQuestions.map((question) => {
      total += question.score
      const submitted = answers[question.id]
      const correct = submitted === question.answerIndex
      if (correct) score += question.score
      bumpMastery(workspace, question.knowledgePointId, correct ? 6 : -4)
      return {
        id: question.id,
        correct,
        earnedScore: correct ? question.score : 0,
        explanation: question.explanation,
        mastery: workspace.knowledgePoints.find((kp) => kp.id === question.knowledgePointId)?.mastery ?? 50,
        generatedSimilarCount: 0,
      }
    })
    workspace.mockResult = { submittedAt: nowIso(), score, total, answers, results }
    if (!workspace.practiceAnswers) workspace.practiceAnswers = {}
    for (const question of workspace.mockQuestions) {
      const submitted = answers[question.id]
      if (submitted === undefined) continue
      const correct = submitted === question.answerIndex
      workspace.practiceAnswers[question.id] = {
        answerIndex: typeof submitted === 'number' ? submitted : -1,
        correct,
        explanation: question.explanation,
        mastery: workspace.knowledgePoints.find((kp) => kp.id === question.knowledgePointId)?.mastery ?? 50,
        answeredAt: nowIso(),
        mode: '模拟卷',
      }
    }
    return {
      score,
      total,
      results,
      workspace: replaceWorkspace(courseId, workspace),
    } satisfies MockSubmitResult
  },

  async clearCoursePracticeAnswer(courseId, questionId) {
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    if (workspace.practiceAnswers) delete workspace.practiceAnswers[questionId]
    return replaceWorkspace(courseId, workspace)
  },

  async clearCourseMockResult(courseId) {
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    workspace.mockResult = null
    return replaceWorkspace(courseId, workspace)
  },

  /* ---------------- workspace 变更 ---------------- */

  async updateCourseWorkspace(courseId, payload) {
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    if (payload.tasks) {
      const previous = workspace.tasks
      workspace.tasks = payload.tasks
      for (const task of workspace.tasks) {
        const before = previous.find((item) => item.id === task.id)
        if (before && before.status !== task.status) {
          applyTaskStatusSideEffects(workspace, task.id, task.status)
        }
      }
      workspace.course.progress = recomputeCourseProgress(workspace)
    }
    if (payload.wrongAnswers) workspace.wrongAnswers = payload.wrongAnswers
    if (payload.note !== undefined) workspace.note = payload.note
    return replaceWorkspace(courseId, workspace)
  },

  flushCourseWorkspaceNote(): void {
    // 演示模式笔记仅存内存；此处为页面卸载兜底，无需持久化。
  },

  async recordCourseTimeLog(courseId, payload) {
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    const existing = payload.clientEntryId
      ? (workspace.timeLog ?? []).find((item) => item.id === payload.clientEntryId)
      : undefined
    if (existing) return { entry: existing, dailyProgress: workspace.dailyProgress! }
    const entry: TimeLogEntry = {
      id: payload.clientEntryId || `log-${Date.now()}`,
      taskId: payload.taskId ?? '',
      date: payload.date ?? toIsoDate(new Date()),
      minutes: payload.minutes,
      note: payload.note ?? '',
      createdAt: nowIso(),
    }
    workspace.timeLog = [...(workspace.timeLog ?? []), entry]
    const updated = replaceWorkspace(courseId, workspace)
    return { entry, dailyProgress: updated.dailyProgress! }
  },

  flushCourseTimeLog(): void {
    // 演示模式只保存在当前页面内存；关闭页面无需网络兜底。
  },

  async deleteCourseTimeLog(courseId, entryId) {
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    workspace.timeLog = (workspace.timeLog ?? []).filter((entry) => entry.id !== entryId)
    const updated = replaceWorkspace(courseId, workspace)
    return { dailyProgress: updated.dailyProgress! }
  },

  /* ---------------- AI 伴学 ---------------- */

  async askCourseAgent(courseId, message, mode) {
    await delay(900)
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    const script = matchAgentScript(message, mode, workspace.course.name)
    const reply = fillScriptPlaceholders(script.reply, scriptStats(workspace))
    appendMessages(workspace, message, reply, mode)
    let proposal: AdjustmentProposal | null = null
    if (script.proposal) {
      proposal = { ...script.proposal, courseId }
      workspace.pendingProposals = [...(workspace.pendingProposals ?? []), proposal]
    }
    return {
      reply,
      workspace: replaceWorkspace(courseId, workspace),
      proposal,
      runId: `run-demo-${Date.now()}`,
      sources: [],
    }
  },

  streamCourseAgent(courseId, message, mode, handlers, _context) {
    let cancelled = false
    const timers: number[] = []
    let step = 0

    const schedule = (fn: () => void, ms: number) => {
      const timer = window.setTimeout(() => {
        if (cancelled) return
        fn()
      }, ms)
      timers.push(timer)
    }

    void (async () => {
      const workspace = await decoratedWorkspaceAsync(courseId).catch(() => null)
      if (!workspace || cancelled) return
      const script = matchAgentScript(message, mode, workspace.course.name)
      const reply = fillScriptPlaceholders(script.reply, scriptStats(workspace))
      const toolEvents = mode === 'agent' ? script.toolEvents : []
      let elapsed = 300

      if (toolEvents.length) {
        schedule(() => handlers.onStep?.(++step), elapsed)
        for (const event of toolEvents) {
          elapsed += 350
          const startAt = elapsed
          schedule(() => handlers.onToolStart?.({ step: step, name: event.name, label: event.label }), startAt)
          elapsed += 700
          schedule(() => handlers.onToolEnd?.({ step: step, name: event.name, summary: event.summary }), elapsed)
        }
      }

      // 按 2-4 字符为 chunk 模拟打字机
      const chunks = reply.match(/[\s\S]{1,3}/g) ?? [reply]
      let cursor = 0
      for (const chunk of chunks) {
        elapsed += 18 + Math.random() * 30
        schedule(() => {
          cursor += chunk.length
          handlers.onToken(chunk)
        }, elapsed)
      }

      elapsed += 200
      schedule(() => {
        if (cancelled) return
        // 对齐后端：done 前把本轮消息追加进 workspace
        const finalWorkspace = decoratedWorkspace(courseId)
        appendMessages(finalWorkspace, message, reply, mode)
        let proposal: AdjustmentProposal | null = null
        if (script.proposal) {
          proposal = { ...script.proposal, courseId }
          finalWorkspace.pendingProposals = [...(finalWorkspace.pendingProposals ?? []), proposal]
        }
        handlers.onDone({
          reply,
          workspace: replaceWorkspace(courseId, finalWorkspace),
          proposal,
          runId: `run-demo-${Date.now()}`,
          sources: [],
        })
      }, elapsed)
    })()

    return {
      cancel: () => {
        cancelled = true
        for (const timer of timers) window.clearTimeout(timer)
      },
    }
  },

  /* ---------------- 策略草稿对话修订（演示版） ---------------- */

  streamStrategyRevision(
    _courseId: string,
    payload: { message: string; history: StrategyRevisionMessage[]; reviewPlan: string; coursePrompt: string },
    handlers: localApi.StrategyRevisionHandlers,
  ): localApi.AgentStreamHandle {
    let cancelled = false
    const timers: number[] = []
    const schedule = (fn: () => void, ms: number) => {
      const timer = window.setTimeout(() => {
        if (!cancelled) fn()
      }, ms)
      timers.push(timer)
    }
    void (async () => {
      await delay(200)
      if (cancelled) return
      // 演示变换：识别"减负/太满"类诉求 → 复习计划末尾追加调整说明行；其余诉求在课程 Prompt 追加一条用户要求
      const wantsLighter = /减负|太满|太多|压缩|减少/.test(payload.message)
      const reply = wantsLighter
        ? '已把第 3 天的学习块从 5 个压缩到 3 个，腾出的 40 分钟挪给错题复盘；其余天次保持不变，两份草稿都已更新，可在左侧预览确认。'
        : `已按「${payload.message.slice(0, 24)}」调整两份草稿：复习计划的相应天次加重了对应知识点，课程总 Prompt 也补充了这条偏好。请在左侧预览确认。`
      const reviewPlan = wantsLighter
        ? payload.reviewPlan.replace('#### 当日时间表', '#### 当日时间表（已减负：合并 2 个学习块，腾出 40 分钟错题复盘）')
        : `${payload.reviewPlan.trimEnd()}\n\n> 演示修订：${payload.message.slice(0, 40)}\n`
      const coursePrompt = `${payload.coursePrompt.trimEnd()}\n- 演示修订：${payload.message.slice(0, 40)}\n`
      const chunks = reply.match(/[\s\S]{1,3}/g) ?? [reply]
      let elapsed = 300
      for (const chunk of chunks) {
        elapsed += 18 + Math.random() * 30
        schedule(() => handlers.onToken(chunk), elapsed)
      }
      elapsed += 200
      schedule(() => handlers.onDone({ reply, reviewPlan, coursePrompt }), elapsed)
    })()
    return {
      cancel: () => {
        cancelled = true
        for (const timer of timers) window.clearTimeout(timer)
      },
    }
  },

  /* ---------------- 提案 / 计划调整 ---------------- */

  async applyCourseAdjustmentProposal(courseId, proposalId) {
    await delay(600)
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    const pending = (workspace.pendingProposals ?? []).find((item) => item.id === proposalId)
    if (!pending) throw new Error('提案不存在或已处理')
    pending.status = 'applied'
    if (pending.params?.dailyHours) workspace.course.dailyHours = pending.params.dailyHours
    if (pending.params?.days) {
      workspace.course.examDate = toIsoDate(new Date(Date.now() + pending.params.days * 86_400_000))
    }
    workspace.pendingProposals = (workspace.pendingProposals ?? []).map((item) => (item.id === proposalId ? pending : item))
    return { workspace: replaceWorkspace(courseId, workspace), proposal: pending }
  },

  async dismissCourseAdjustmentProposal(courseId, proposalId) {
    await delay(300)
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    const pending = (workspace.pendingProposals ?? []).find((item) => item.id === proposalId)
    if (!pending) throw new Error('提案不存在或已处理')
    pending.status = 'dismissed'
    workspace.pendingProposals = (workspace.pendingProposals ?? []).map((item) => (item.id === proposalId ? pending : item))
    replaceWorkspace(courseId, workspace)
    return pending
  },

  async adjustCoursePlan(courseId, payload: PlanParamsAdjustRequest): Promise<PlanParamsAdjustResponse> {
    await delay(700)
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    if (payload.examDate) workspace.course.examDate = payload.examDate
    if (payload.dailyHours) workspace.course.dailyHours = payload.dailyHours
    if (payload.days && workspace.onboarding) workspace.onboarding.days = payload.days
    // 对齐后端两分支：仅改考试日期直接返回 workspace；改天数/时长返回提案
    if (!payload.days && !payload.dailyHours) {
      return { workspace: replaceWorkspace(courseId, workspace), proposal: null }
    }
    const proposal: AdjustmentProposal = {
      id: `proposal-plan-${Date.now()}`,
      courseId,
      title: '计划参数调整',
      reason: '你调整了复习天数或每日时长。',
      impact: '任务将按新参数重新装包。',
      status: 'pending',
      params: payload,
    }
    return { workspace: null, proposal }
  },

  /* ---------------- MCP / 外部资料 ---------------- */

  async listMcpServers() {
    const data = await loadSnapshot()
    return data.mcpServers
  },

  async saveMcpServer(payload) {
    const data = await loadSnapshot()
    const server: McpServer = {
      id: payload.id || `mcp-demo-${Date.now()}`,
      name: payload.name,
      endpoint: payload.endpoint,
      transport: payload.transport,
      command: payload.command,
      args: payload.args,
      tools: [],
      allowedTools: payload.allowedTools,
    }
    const index = data.mcpServers.findIndex((item) => item.id === server.id)
    if (index === -1) data.mcpServers.push(server)
    else data.mcpServers[index] = server
    return server
  },

  async discoverMcpServer(serverId) {
    await delay(1000)
    const data = await loadSnapshot()
    const server = data.mcpServers.find((item) => item.id === serverId)
    if (!server) throw new Error('MCP 服务不存在')
    return server
  },

  async getBilibiliCredentialStatus() {
    return { configured: false, source: 'none' as const }
  },

  async verifyBilibiliCredentials() {
    return { loggedIn: null, message: '演示模式不支持真实凭据校验。', nextSteps: [] }
  },

  async saveBilibiliCredentials() {
    return { configured: true, source: 'app' as const }
  },

  async clearBilibiliCredentials() {
    return { configured: false, source: 'none' as const }
  },

  async submitCourseExternalSource(courseId, payload) {
    await loadSnapshot()
    const source: ExternalSource = {
      id: `source-demo-${Date.now()}`,
      courseId,
      url: payload.url,
      sourceType: payload.sourceType,
      title: payload.url,
      status: 'queued',
      content: '',
      metadata: { mcpServerId: payload.mcpServerId, toolName: payload.toolName },
      error: '',
      createdAt: nowIso(),
      updatedAt: nowIso(),
    }
    externalSources.set(source.id, source)
    // 异步推进抓取状态，对齐后端 queued → fetching → pending_review 流转
    window.setTimeout(() => {
      const current = externalSources.get(source.id)
      if (current && current.status === 'queued') current.status = 'fetching'
    }, 1500)
    window.setTimeout(() => {
      const current = externalSources.get(source.id)
      if (current && current.status === 'fetching') {
        current.status = 'pending_review'
        current.title = '演示抓取的网页内容'
        current.content = `# 演示抓取结果\n\n这是演示模式对外部资料 ${payload.url} 的模拟抓取结果。完整版会通过对应的 MCP 服务抓取真实内容，经你审核后导入资料库。\n\n## 要点\n\n- 演示模式不发出真实网络请求；\n- 审核通过后会以「外部资料」形式加入课程资料库。`
      }
    }, 3200)
    return source
  },

  async getCourseExternalSource(courseId, sourceId) {
    const source = externalSources.get(sourceId)
    if (!source || source.courseId !== courseId) throw new Error('外部资料不存在')
    return source
  },

  async approveCourseExternalSource(courseId, sourceId) {
    await delay(400)
    const source = externalSources.get(sourceId)
    if (!source) throw new Error('外部资料不存在')
    source.status = 'approved'
    const workspace = decoratedWorkspace(courseId)
    workspace.materials.push({
      name: `外部资料-${source.title}.md`,
      relativePath: `外部资料/${source.title}.md`,
      type: 'MD',
      size: source.content.length,
      detail: `${(source.content.length / 1024).toFixed(1)} KB · 演示导入`,
      previewStatus: 'ready',
      previewLabel: '可预览',
      previewMessage: '外部资料已导入（演示）。',
    })
    return { source: { ...source }, workspace: replaceWorkspace(courseId, workspace) }
  },

  async dismissCourseExternalSource(courseId, sourceId) {
    const source = externalSources.get(sourceId)
    if (!source || source.courseId !== courseId) throw new Error('外部资料不存在')
    source.status = 'dismissed'
    return { ...source }
  },

  async deleteCourseWrongAnswer(courseId, wrongAnswerId) {
    await loadSnapshot()
    const workspace = decoratedWorkspace(courseId)
    const removed = workspace.wrongAnswers.find((item) => item.id === wrongAnswerId)
    workspace.wrongAnswers = workspace.wrongAnswers.filter((item) => item.id !== wrongAnswerId)
    const data = requireSnapshot()
    const archiveItem: ArchiveItemApiResponse = {
      id: `archive-demo-${Date.now()}`,
      item_type: 'wrong-answer',
      entity_id: wrongAnswerId,
      title: removed?.title ?? '已删除错题',
      course_id: courseId,
      course_name: workspace.course.name,
      deleted_at: nowIso(),
      purge_after: new Date(Date.now() + 7 * 86_400_000).toISOString(),
    }
    data.archive.push(archiveItem)
    return {
      workspace: replaceWorkspace(courseId, workspace),
      archiveItem: toArchiveItem(archiveItem),
    }
  },

  async listArchiveItems() {
    const data = await loadSnapshot()
    return data.archive.map(toArchiveItem)
  },

  async permanentlyDeleteArchiveItem(archiveId) {
    const data = await loadSnapshot()
    const index = data.archive.findIndex((item) => item.id === archiveId)
    if (index === -1) throw new Error('归档内容不存在')
    data.archive.splice(index, 1)
    return { deleted: true, archiveItems: data.archive.map(toArchiveItem) }
  },

  async restoreArchiveItem(archiveId) {
    const data = await loadSnapshot()
    const index = data.archive.findIndex((item) => item.id === archiveId)
    if (index === -1) throw new Error('归档内容不存在')
    const [item] = data.archive.splice(index, 1)
    if (item.item_type === 'course') {
      const restored: CourseApiResponse = {
        id: item.entity_id,
        name: item.title,
        exam_date: toIsoDate(new Date(Date.now() + 14 * 86_400_000)),
        target_score: 85,
        daily_hours: 3,
        progress: 0,
      }
      data.courses.push(restored)
      return { itemType: item.item_type, course: toCourse(restored), workspace: undefined, archiveItems: data.archive.map(toArchiveItem) }
    }
    const workspace = decoratedWorkspace(item.course_id ?? '')
    workspace.wrongAnswers.push({
      id: item.entity_id,
      title: item.title,
      tag: '已恢复',
      mistakeType: '历史错题',
      count: 1,
      isReviewed: false,
    })
    return {
      itemType: item.item_type,
      course: undefined,
      workspace: replaceWorkspace(item.course_id ?? '', workspace),
      archiveItems: data.archive.map(toArchiveItem),
    }
  },

  toRuntimeModelProfile(runtimeModel): ModelProfile {
    return {
      provider: 'custom',
      baseUrl: runtimeModel.baseUrl,
      model: runtimeModel.model,
      apiKey: '',
      hasApiKey: runtimeModel.hasApiKey,
      availableModels: runtimeModel.availableModels,
      supportsVision: true,
      status: runtimeModel.connected ? 'connected' : 'unconfigured',
      statusMessage: runtimeModel.connected ? '已由本机服务配置并连接' : '本机模型尚未配置',
    }
  },

  /** 纯转换函数：直接复用真实实现，保证 demo 与本地后端形状一致。 */
  toGlossaryTerm: localApi.toGlossaryTerm,
  toGlossaryStatus: localApi.toGlossaryStatus,
}

async function decoratedWorkspaceAsync(courseId: string): Promise<StudyWorkspace> {
  await loadSnapshot()
  return decoratedWorkspace(courseId)
}

/* ------------------------------------------------------------------ */
/* 术语词条辅助（快照 glossaries 可选，缺失时返回空表） */

function toGlossaryResponse(courseId: string, entry: GlossaryApiResponse | undefined): GlossaryResponse {
  const terms = (entry?.terms ?? []).map(localApi.toGlossaryTerm)
  const statusResponse = entry?.status ?? {}
  return {
    courseId,
    terms,
    status: localApi.toGlossaryStatus(courseId, {
      courseId,
      status: statusResponse.status ?? 'idle',
      termsTotal: statusResponse.termsTotal ?? terms.length,
      termsActive: statusResponse.termsActive ?? terms.filter((term) => term.status === 'active').length,
      lastError: statusResponse.lastError ?? '',
      lastRefreshedAt: statusResponse.lastRefreshedAt ?? '',
    }),
  }
}

function mutableGlossaryEntry(data: DemoSnapshot, courseId: string): GlossaryApiResponse {
  if (!data.glossaries) data.glossaries = {}
  const existing = data.glossaries[courseId]
  if (existing) return existing
  const created: GlossaryApiResponse = {
    courseId,
    terms: [],
    status: { status: 'idle', termsTotal: 0, termsActive: 0, lastError: '', lastRefreshedAt: '' },
  }
  data.glossaries[courseId] = created
  return created
}

/* ------------------------------------------------------------------ */
/* 演示 job 推进（approve-job → queued → running → completed） */

type DemoJob = AgentJob & { startedAtMs: number }

const jobs = new Map<string, DemoJob>()

function registerJob(courseId: string, jobType: AgentJob['jobType'] = 'strategy_documents_approve'): string {
  const id = `job-demo-${Date.now()}`
  jobs.set(id, {
    id,
    courseId,
    jobType,
    status: 'queued',
    attempts: 1,
    maxAttempts: 3,
    error: '',
    result: {},
    createdAt: nowIso(),
    updatedAt: nowIso(),
    startedAtMs: Date.now(),
  })
  return id
}

async function getJob(jobId: string): Promise<AgentJob> {
  const job = jobs.get(jobId)
  if (!job) throw new Error('任务不存在')
  const elapsed = Date.now() - job.startedAtMs
  if (job.status === 'completed') return { ...job }
  if (elapsed > 6000) {
    job.status = 'completed'
    job.updatedAt = nowIso()
  } else if (elapsed > 1200) {
    job.status = 'running'
    job.updatedAt = nowIso()
  }
  return { ...job }
}

/* 外部资料 store（不入快照） */
const externalSources = new Map<string, ExternalSource>()

export default demoApi
