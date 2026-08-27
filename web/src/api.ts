import { authFetch } from './auth'
import type {
  AccountProfile,
  AdjustmentProposal,
  AgentJob,
  ArchiveItem,
  BilibiliCredentialStatus,
  BilibiliCredentialVerifyResult,
  Course,
  CourseFeedbackApplyResult,
  CourseFeedbackRefineResult,
  CourseFeedbackRequest,
  CourseFeedbackRules,
  CourseFeedbackSubmitResult,
  GlobalCourseFeedbackResult,
  CourseMindMap,
  DailyProgress,
  EmbeddingProfile,
  ExternalSource,
  GlossaryResponse,
  GlossaryStatus,
  GlossaryTerm,
  KnowledgeBaseStatus,
  MaterialPreview,
  McpServer,
  MockAnswer,
  MockSubmitResult,
  ModelProfile,
  PlanParamsAdjustRequest,
  PlanParamsAdjustResponse,
  PlanTask,
  PracticeAnswerResult,
  SearchResult,
  StrategyDocuments,
  StrategyGenerationRequest,
  StrategyRevisionMessage,
  StrategyRevisionStreamDone,
  StudyWorkspace,
  TimeLogEntry,
  UserProfilePrompt,
  WrongAnswer,
} from './types'

// 生产同域留空走相对路径（nginx 反代 /api）；本地开发走 vite proxy；特殊部署用 VITE_API_BASE_URL 覆盖
export const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '') + '/api'

function encodeMaterialPath(relativePath: string) {
  return relativePath.split('/').map(encodeURIComponent).join('/')
}

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

type CourseCreatePayload = {
  name: string
  examDate: string
  targetScore: number
  dailyHours: number
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

type WrongAnswerArchiveApiResponse = {
  workspace: StudyWorkspace
  archive_item: ArchiveItemApiResponse
}

type RestoreArchiveApiResponse = {
  item_type: ArchiveItem['itemType']
  course?: CourseApiResponse
  workspace?: StudyWorkspace
  archive_items: ArchiveItemApiResponse[]
}

type CourseMindMapApiResponse = {
  status: 'ready' | 'empty'
  courseId: string
  mindMap: CourseMindMap | null
}

async function request<T>(path: string, init?: RequestInit, timeoutMs?: number): Promise<T> {
  const controller = timeoutMs ? new AbortController() : null
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null
  let response: Response
  try {
    response = await authFetch(path, {
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        ...init?.headers,
      },
      ...init,
      signal: controller ? controller.signal : init?.signal,
    })
  } catch (error) {
    if (controller && controller.signal.aborted) {
      throw new Error(`请求超时（${Math.round((timeoutMs ?? 0) / 1000)} 秒无响应），请稍后重试。`)
    }
    throw error
  } finally {
    if (timer) clearTimeout(timer)
  }

  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(typeof body.detail === 'string' ? body.detail : '本地服务请求失败')
  }
  return body as T
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

export async function listCourses() {
  const courses = await request<CourseApiResponse[]>('/courses')
  return courses.map(toCourse)
}

export async function createCourse(payload: CourseCreatePayload) {
  const course = await request<CourseApiResponse>('/courses', {
    method: 'POST',
    body: JSON.stringify({
      name: payload.name,
      exam_date: payload.examDate,
      target_score: payload.targetScore,
      daily_hours: payload.dailyHours,
    }),
  })
  return toCourse(course)
}

export async function deleteCourse(courseId: string) {
  const archiveItem = await request<ArchiveItemApiResponse>(`/courses/${encodeURIComponent(courseId)}`, {
    method: 'DELETE',
  })
  return toArchiveItem(archiveItem)
}

export function getCourseWorkspace(courseId: string) {
  return request<StudyWorkspace>(`/courses/${encodeURIComponent(courseId)}/workspace`)
}

export function reviewCourseReadability(courseId: string) {
  return request<StudyWorkspace>(`/courses/${encodeURIComponent(courseId)}/readability-review`, { method: 'POST' })
}

export function getCourseMindMap(courseId: string) {
  return request<CourseMindMapApiResponse>(`/courses/${encodeURIComponent(courseId)}/mind-map`)
}

export function generateCourseMindMap(courseId: string) {
  return request<CourseMindMapApiResponse>(`/courses/${encodeURIComponent(courseId)}/mind-map/generate`, {
    method: 'POST',
  })
}

export function regroupCourseMindMapModules(courseId: string) {
  return request<CourseMindMapApiResponse>(`/courses/${encodeURIComponent(courseId)}/mind-map/regroup-modules`, {
    method: 'POST',
  })
}

export function saveCourseMindMap(courseId: string, mindMap: CourseMindMap) {
  return request<CourseMindMapApiResponse>(`/courses/${encodeURIComponent(courseId)}/mind-map`, {
    method: 'PUT',
    body: JSON.stringify(mindMap),
  })
}

export async function searchCourse(courseId: string, query: string) {
  const response = await request<{ query: string; results: SearchResult[] }>(
    `/courses/${encodeURIComponent(courseId)}/search?q=${encodeURIComponent(query)}`,
  )
  return response.results
}

export function saveCourseSetup(courseId: string, payload: {
  courseName: string
  examDate: string
  targetScore: number
  targetText: string
  dailyHours: number
  days: number
  reviewCount: number
  examFormat: string
  remarks: string
  contentStyle: 'standard' | 'dialogue' | 'story'
}) {
  return request<StudyWorkspace>(`/courses/${encodeURIComponent(courseId)}/setup`, {
    method: 'POST',
    body: JSON.stringify({
      course_name: payload.courseName,
      exam_date: payload.examDate,
      target_score: payload.targetScore,
      target_text: payload.targetText,
      daily_hours: payload.dailyHours,
      days: payload.days,
      review_count: payload.reviewCount,
      exam_format: payload.examFormat,
      remarks: payload.remarks,
      content_style: payload.contentStyle,
    }),
  })
}

export function submitCourseDiagnostic(courseId: string, answers: Record<string, number>) {
  return request<StudyWorkspace>(`/courses/${encodeURIComponent(courseId)}/diagnostic/submit`, {
    method: 'POST',
    body: JSON.stringify({ answers }),
  })
}

export function getStrategyDocuments(courseId: string) {
  return request<StrategyDocuments>(`/courses/${encodeURIComponent(courseId)}/strategy-documents`)
}

export function generateStrategyDocuments(courseId: string) {
  return request<StrategyDocuments>(`/courses/${encodeURIComponent(courseId)}/strategy-documents/generate`, {
    method: 'POST',
  })
}

export function saveStrategyDocuments(
  courseId: string,
  payload: { reviewPlan: string; coursePrompt: string; reviewPlanVersion: number; coursePromptVersion: number },
) {
  return request<StrategyDocuments>(`/courses/${encodeURIComponent(courseId)}/strategy-documents`, {
    method: 'PUT',
    body: JSON.stringify({
      review_plan: payload.reviewPlan,
      course_prompt: payload.coursePrompt,
      review_plan_version: payload.reviewPlanVersion,
      course_prompt_version: payload.coursePromptVersion,
    }),
  })
}

export function approveStrategyDocuments(
  courseId: string,
  payload: StrategyGenerationRequest,
) {
  return request<StudyWorkspace>(`/courses/${encodeURIComponent(courseId)}/strategy-documents/approve`, {
    method: 'POST',
    body: JSON.stringify({
      review_plan: payload.reviewPlan,
      course_prompt: payload.coursePrompt,
      review_plan_version: payload.reviewPlanVersion,
      course_prompt_version: payload.coursePromptVersion,
      repair_only: payload.repairOnly ?? false,
      generation_mode: payload.generationMode ?? 'all',
      lesson_limit: payload.lessonLimit ?? null,
      continue_generation: payload.continueGeneration ?? false,
    }),
  })
}

export function approveStrategyDocumentsInBackground(
  courseId: string,
  payload: StrategyGenerationRequest,
) {
  return request<{ jobId: string; courseId: string }>(`/courses/${encodeURIComponent(courseId)}/strategy-documents/approve-job`, {
    method: 'POST',
    body: JSON.stringify({
      review_plan: payload.reviewPlan,
      course_prompt: payload.coursePrompt,
      review_plan_version: payload.reviewPlanVersion,
      course_prompt_version: payload.coursePromptVersion,
      repair_only: payload.repairOnly ?? false,
      generation_mode: payload.generationMode ?? 'all',
      lesson_limit: payload.lessonLimit ?? null,
      continue_generation: payload.continueGeneration ?? false,
    }),
  })
}

export function getAgentJob(jobId: string) {
  return request<AgentJob>(`/agent-jobs/${encodeURIComponent(jobId)}`)
}

export function cancelAgentJob(jobId: string) {
  return request<AgentJob>(`/agent-jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' })
}

export function saveCoursePrompt(courseId: string, coursePrompt: string, version: number) {
  return request<StrategyDocuments>(`/courses/${encodeURIComponent(courseId)}/course-prompt`, {
    method: 'PUT',
    body: JSON.stringify({ course_prompt: coursePrompt, version }),
  })
}

export function submitCourseFeedback(courseId: string, payload: CourseFeedbackRequest) {
  return request<CourseFeedbackSubmitResult>(`/courses/${encodeURIComponent(courseId)}/course-feedback`, {
    method: 'POST',
    body: JSON.stringify({
      selected_text: payload.selectedText,
      user_comment: payload.userComment,
      context: payload.context ?? {},
    }),
  })
}

export function submitGlobalCourseFeedback(courseId: string, taskId: string, sectionId: string, sectionIndex: number, userComment: string) {
  return request<GlobalCourseFeedbackResult>(`/courses/${encodeURIComponent(courseId)}/course-feedback/global`, {
    method: 'POST',
    body: JSON.stringify({ task_id: taskId, section_id: sectionId, section_index: sectionIndex, user_comment: userComment }),
  }, 180000)
}

export function applyGlobalCourseFeedback(courseId: string, feedbackId: string) {
  return request<CourseFeedbackApplyResult>(`/courses/${encodeURIComponent(courseId)}/course-feedback/${encodeURIComponent(feedbackId)}/global/apply`, {
    method: 'POST',
  }, 120000)
}

export function getCourseFeedbackRules(courseId: string) {
  return request<CourseFeedbackRules>(`/courses/${encodeURIComponent(courseId)}/course-feedback/rules`)
}

export function refineCourseFeedbackRewrite(courseId: string, feedbackId: string, extraComment: string, previousRewrite: string) {
  return request<CourseFeedbackRefineResult>(`/courses/${encodeURIComponent(courseId)}/course-feedback/${encodeURIComponent(feedbackId)}/rewrite/refine`, {
    method: 'POST',
    body: JSON.stringify({ extra_comment: extraComment, previous_rewrite: previousRewrite }),
  }, 120000)
}

export function applyCourseFeedbackRewrite(courseId: string, feedbackId: string, originalText: string, rewrittenText: string, target: CourseFeedbackRequest['context']) {
  return request<CourseFeedbackApplyResult>(`/courses/${encodeURIComponent(courseId)}/course-feedback/${encodeURIComponent(feedbackId)}/rewrite/apply`, {
    method: 'POST',
    body: JSON.stringify({ original_text: originalText, rewritten_text: rewrittenText, target: target ?? {} }),
  }, 120000)
}

export function getCourseMaterialPreview(courseId: string, relativePath: string) {
  return request<MaterialPreview>(
    `/courses/${encodeURIComponent(courseId)}/materials/preview/${encodeMaterialPath(relativePath)}`,
  )
}

export function getCourseMaterialFileUrl(courseId: string, relativePath: string) {
  return `${apiBaseUrl}/courses/${encodeURIComponent(courseId)}/materials/file/${encodeMaterialPath(relativePath)}`
}

export function getCourseMaterialConvertedFileUrl(courseId: string, relativePath: string) {
  return `${apiBaseUrl}/courses/${encodeURIComponent(courseId)}/materials/converted-file/${encodeMaterialPath(relativePath)}`
}

export function rescanCourseMaterials(courseId: string) {
  return request<StudyWorkspace>(`/courses/${encodeURIComponent(courseId)}/materials/rescan`, { method: 'POST' })
}

export async function uploadCourseMaterials(courseId: string, files: FileList | File[], role: 'primary' | 'supplementary' = 'supplementary') {
  const fileArray = Array.from(files)
  const manifest = fileArray.map((file) => ({ name: file.name, size: file.size, type: file.type }))
  const encoder = new TextEncoder()
  const manifestBytes = encoder.encode(JSON.stringify(manifest))
  const headerBytes = encoder.encode(`${manifestBytes.byteLength}\n`)
  const response = await authFetch(`/courses/${encodeURIComponent(courseId)}/materials/upload-batch?role=${encodeURIComponent(role)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: new Blob([headerBytes, manifestBytes, ...fileArray]),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '资料批量导入失败')
  return body as StudyWorkspace
}

export function updateCourseMaterialRole(
  courseId: string,
  relativePath: string,
  payload: { role: 'primary' | 'supplementary'; priorityOrder?: number },
) {
  return request<StudyWorkspace>(
    `/courses/${encodeURIComponent(courseId)}/materials/${encodeMaterialPath(relativePath)}/role`,
    { method: 'PATCH', body: JSON.stringify(payload) },
  )
}

export function deleteCourseMaterial(courseId: string, relativePath: string) {
  return request<StudyWorkspace>(
    `/courses/${encodeURIComponent(courseId)}/materials/${encodeMaterialPath(relativePath)}`,
    { method: 'DELETE' },
  )
}

export function getRuntimeModel() {
  return request<RuntimeModel>('/runtime-model')
}

export type ModelUsageSnapshot = {
  promptTokens: number
  completionTokens: number
  totalTokens: number
  calls: number
  failures: number
  startedAt: string
  updatedAt: string
  currentCall: { model: string; startedAt: string }
  recent: Array<{ at: string; model: string; promptTokens: number; completionTokens: number; totalTokens: number }>
}

export function getModelUsage() {
  return request<ModelUsageSnapshot>('/model-usage')
}

export function saveRuntimeModel(payload: { baseUrl: string; apiKey: string; model: string }) {
  return request<RuntimeModel>('/runtime-model', {
    method: 'PUT',
    body: JSON.stringify({
      base_url: payload.baseUrl,
      api_key: payload.apiKey,
      model: payload.model,
    }),
  })
}

export type ModelProfilesResponse = {
  active: string
  profiles: Record<string, { baseUrl: string; model: string; hasApiKey: boolean }>
}

export function getModelProfiles() {
  return request<ModelProfilesResponse>('/model-profiles')
}

export function saveModelProfile(provider: string, payload: { baseUrl: string; apiKey: string; model: string }) {
  return request<ModelProfilesResponse>(`/model-profiles/${encodeURIComponent(provider)}`, {
    method: 'PUT',
    body: JSON.stringify({
      base_url: payload.baseUrl,
      api_key: payload.apiKey,
      model: payload.model,
    }),
  })
}

export type BackupModelProfile = {
  baseUrl: string
  model: string
  hasApiKey: boolean
  connected: boolean
}

export function getBackupModel() {
  return request<BackupModelProfile>('/backup-model')
}

export function saveBackupModel(payload: { baseUrl: string; apiKey: string; model: string }) {
  return request<BackupModelProfile>('/backup-model', {
    method: 'PUT',
    body: JSON.stringify({
      base_url: payload.baseUrl,
      api_key: payload.apiKey,
      model: payload.model,
    }),
  })
}

function normalizeAccountProfile(profile: AccountProfile & { display_name?: string; avatar_url?: string }): AccountProfile {
  return {
    id: profile.id,
    email: profile.email,
    displayName: profile.displayName ?? profile.display_name ?? '',
    role: profile.role,
    avatarUrl: profile.avatarUrl ?? profile.avatar_url ?? '',
    gender: profile.gender ?? '',
    age: profile.age ?? null,
    signature: profile.signature ?? '',
  }
}

export function getAccountProfile() {
  return request<AccountProfile & { display_name?: string; avatar_url?: string }>('/account-profile').then(normalizeAccountProfile)
}

export function saveAccountProfile(payload: {
  displayName: string
  gender: string
  age: number | null
  signature: string
}) {
  return request<AccountProfile & { display_name?: string; avatar_url?: string }>('/account-profile', {
    method: 'PUT',
    body: JSON.stringify({
      display_name: payload.displayName,
      gender: payload.gender,
      age: payload.age,
      signature: payload.signature,
    }),
  }).then(normalizeAccountProfile)
}

async function parseAccountProfileResponse(response: Response, fallbackMessage: string) {
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : fallbackMessage)
  return normalizeAccountProfile(body as AccountProfile & { display_name?: string; avatar_url?: string })
}

export async function uploadAccountAvatar(file: File) {
  const formData = new FormData()
  formData.append('avatar', file)
  const response = await authFetch('/account-profile/avatar', { method: 'POST', body: formData })
  return parseAccountProfileResponse(response, '头像上传失败')
}

export async function deleteAccountAvatar() {
  const response = await authFetch('/account-profile/avatar', { method: 'DELETE' })
  return parseAccountProfileResponse(response, '头像删除失败')
}

export function getUserProfilePrompt() {
  return request<UserProfilePrompt>('/user-profile')
}

export function saveUserProfilePrompt(content: string) {
  return request<UserProfilePrompt>('/user-profile', {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}

export function getEmbeddingProfile() {
  return request<EmbeddingProfile>('/knowledge/embedding')
}

export function saveEmbeddingProfile(payload: Pick<EmbeddingProfile, 'enabled' | 'baseUrl' | 'model'>) {
  return request<EmbeddingProfile>('/knowledge/embedding', {
    method: 'PUT',
    body: JSON.stringify({
      enabled: payload.enabled,
      base_url: payload.baseUrl,
      model: payload.model,
    }),
  })
}

export function testEmbeddingProfile() {
  return request<EmbeddingProfile & { success: boolean }>('/knowledge/embedding/test', {
    method: 'POST',
  })
}

export function rebuildKnowledgeEmbeddings(courseId: string) {
  return request<EmbeddingProfile>(`/courses/${encodeURIComponent(courseId)}/knowledge/reindex`, {
    method: 'POST',
  })
}

export function getKnowledgeBaseStatus(courseId: string) {
  return request<KnowledgeBaseStatus>(`/courses/${encodeURIComponent(courseId)}/knowledge/status`)
}

export function submitCoursePracticeAnswer(
  courseId: string,
  questionId: string,
  answerIndex: number,
  mode: '主线学习' | '刷题练习' = '刷题练习',
) {
  return request<PracticeAnswerResult>(`/courses/${encodeURIComponent(courseId)}/practice/answer`, {
    method: 'POST',
    body: JSON.stringify({ question_id: questionId, answer_index: answerIndex, mode }),
  })
}

export function submitCourseWrongAnswerRetry(courseId: string, wrongAnswerId: string, answerIndex: number) {
  return request<PracticeAnswerResult>(
    `/courses/${encodeURIComponent(courseId)}/wrong-answers/${encodeURIComponent(wrongAnswerId)}/retry`,
    { method: 'POST', body: JSON.stringify({ answer_index: answerIndex }) },
  )
}

export function repairCourseMockQuestions(courseId: string, force = false) {
  const query = force ? '?force=true' : ''
  return request<{
    workspace: StudyWorkspace
    repaired: boolean
    source: 'existing' | 'model' | 'fallback'
    warning: string
    questionCount: number
  }>(`/courses/${encodeURIComponent(courseId)}/mock/repair${query}`, { method: 'POST' })
}

export function submitCourseMockAnswers(courseId: string, answers: Record<string, MockAnswer>) {
  return request<MockSubmitResult>(`/courses/${encodeURIComponent(courseId)}/mock/submit`, {
    method: 'POST',
    body: JSON.stringify({ answers }),
  })
}

export function clearCoursePracticeAnswer(courseId: string, questionId: string) {
  return request<StudyWorkspace>(
    `/courses/${encodeURIComponent(courseId)}/practice/answers/${encodeURIComponent(questionId)}`,
    { method: 'DELETE' },
  )
}

export function clearCourseMockResult(courseId: string) {
  return request<StudyWorkspace>(`/courses/${encodeURIComponent(courseId)}/mock/result`, { method: 'DELETE' })
}

export function updateCourseWorkspace(courseId: string, payload: {
  tasks?: PlanTask[]
  wrongAnswers?: WrongAnswer[]
  note?: string
}) {
  return request<StudyWorkspace>(`/courses/${encodeURIComponent(courseId)}/workspace`, {
    method: 'PUT',
    body: JSON.stringify({
      tasks: payload.tasks,
      wrong_answers: payload.wrongAnswers,
      note: payload.note,
    }),
  })
}

/**
 * 页面卸载时的“尽力保存”：keepalive 让浏览器在页面关闭后仍会发出请求，
 * 专门用于捕获尚停留在防抖定时器里、来不及通过 updateCourseWorkspace 发出的笔记。
 * 失败静默——这是最后兜底手段；正常链路由 updateCourseWorkspace + 失败提示负责。
 */
export function flushCourseWorkspaceNote(courseId: string, note: string): void {
  void authFetch(`/courses/${encodeURIComponent(courseId)}/workspace`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ note }),
    keepalive: true,
  }).catch(() => undefined)
}

type TimeLogResponse = {
  entry?: TimeLogEntry
  dailyProgress: DailyProgress
}

export function recordCourseTimeLog(
  courseId: string,
  payload: { taskId?: string; minutes: number; date?: string; note?: string; clientEntryId?: string },
) {
  return request<TimeLogResponse>(`/courses/${encodeURIComponent(courseId)}/time-log`, {
    method: 'POST',
    body: JSON.stringify({
      task_id: payload.taskId ?? '',
      minutes: payload.minutes,
      target_date: payload.date ?? '',
      note: payload.note ?? '',
      client_entry_id: payload.clientEntryId ?? '',
    }),
  })
}

/** 页面离开时尽力写入整分钟；失败会由计时器保留的待提交记录在下次进入时重试。 */
export function flushCourseTimeLog(courseId: string, minutes: number, clientEntryId: string): void {
  void authFetch(`/courses/${encodeURIComponent(courseId)}/time-log`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({
      task_id: '',
      minutes,
      target_date: '',
      note: '',
      client_entry_id: clientEntryId,
    }),
    keepalive: true,
  }).catch(() => undefined)
}

export function deleteCourseTimeLog(courseId: string, entryId: string) {
  return request<TimeLogResponse>(
    `/courses/${encodeURIComponent(courseId)}/time-log/${encodeURIComponent(entryId)}`,
    { method: 'DELETE' },
  )
}

export function askCourseAgent(
  courseId: string,
  message: string,
  mode: 'chat' | 'agent',
  context?: Record<string, unknown>,
) {
  return request<{
    reply: string
    workspace: StudyWorkspace
    proposal?: AdjustmentProposal | null
    runId?: string
    sources?: Array<Record<string, unknown>>
  }>(
    `/courses/${encodeURIComponent(courseId)}/agent/chat`,
    { method: 'POST', body: JSON.stringify({ message, mode, context }) },
  )
}

export type AgentStreamDone = {
  reply: string
  workspace: StudyWorkspace
  proposal?: AdjustmentProposal | null
  sources?: Array<Record<string, unknown>>
  runId?: string
}

export type AgentStreamHandlers = {
  onToken: (text: string) => void
  onStep?: (step: number) => void
  onToolStart?: (event: { step: number; name: string; label: string }) => void
  onToolEnd?: (event: { step: number; name: string; summary: string }) => void
  onWarning?: (message: string) => void
  onDone: (result: AgentStreamDone) => void
  onError: (message: string) => void
}

export type AgentStreamHandle = { cancel: () => void }

function parseAgentSseEvent(rawEvent: string, handlers: AgentStreamHandlers) {
  let eventType = 'message'
  const dataLines: string[] = []
  for (const line of rawEvent.split('\n')) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }
  if (!dataLines.length) return
  let payload: Record<string, unknown>
  try {
    payload = JSON.parse(dataLines.join('\n'))
  } catch {
    return
  }
  switch (eventType) {
    case 'token':
      if (typeof payload.text === 'string') handlers.onToken(payload.text)
      break
    case 'step':
      if (typeof payload.step === 'number' && handlers.onStep) handlers.onStep(payload.step)
      break
    case 'tool_start':
      if (handlers.onToolStart) {
        handlers.onToolStart(payload as { step: number; name: string; label: string })
      }
      break
    case 'tool_end':
      if (handlers.onToolEnd) {
        handlers.onToolEnd(payload as { step: number; name: string; summary: string })
      }
      break
    case 'warning':
      if (handlers.onWarning && typeof payload.message === 'string') handlers.onWarning(payload.message)
      break
    case 'done':
      handlers.onDone(payload as AgentStreamDone)
      break
    case 'error':
      handlers.onError(typeof payload.message === 'string' ? payload.message : 'AI 伴学响应出错。')
      break
    default:
      break
  }
}

export function streamCourseAgent(
  courseId: string,
  message: string,
  mode: 'chat' | 'agent',
  handlers: AgentStreamHandlers,
  context?: Record<string, unknown>,
): AgentStreamHandle {
  const controller = new AbortController()
  let cancelled = false

  void (async () => {
    let response: Response
    try {
      response = await authFetch(
        `/courses/${encodeURIComponent(courseId)}/agent/chat/stream`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, mode, context }),
          signal: controller.signal,
        },
      )
    } catch (error) {
      if (!cancelled) {
        handlers.onError(error instanceof Error ? error.message : '无法连接流式接口。')
      }
      return
    }
    if (!response.ok || !response.body) {
      if (!cancelled) handlers.onError(`流式接口返回异常（HTTP ${response.status}）。`)
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let separatorIndex = buffer.indexOf('\n\n')
        while (separatorIndex >= 0) {
          const rawEvent = buffer.slice(0, separatorIndex)
          buffer = buffer.slice(separatorIndex + 2)
          parseAgentSseEvent(rawEvent, handlers)
          separatorIndex = buffer.indexOf('\n\n')
        }
      }
      if (buffer.trim()) parseAgentSseEvent(buffer, handlers)
    } catch (error) {
      if (!cancelled) {
        handlers.onError(error instanceof Error ? error.message : '读取流式响应失败。')
      }
    }
  })()

  return {
    cancel: () => {
      cancelled = true
      controller.abort()
    },
  }
}

export function applyCourseAdjustmentProposal(courseId: string, proposalId: string) {
  return request<{ workspace: StudyWorkspace; proposal: AdjustmentProposal }>(
    `/courses/${encodeURIComponent(courseId)}/adjustment-proposals/${encodeURIComponent(proposalId)}/apply`,
    { method: 'POST' },
  )
}

export type StrategyRevisionHandlers = {
  onToken: (text: string) => void
  onDone: (result: StrategyRevisionStreamDone) => void
  onError: (message: string) => void
}

/** 对话式修订策略草稿（SSE）。事件协议与 agent/chat/stream 一致：token / done / error。 */
export function streamStrategyRevision(
  courseId: string,
  payload: { message: string; history: StrategyRevisionMessage[]; reviewPlan: string; coursePrompt: string },
  handlers: StrategyRevisionHandlers,
): AgentStreamHandle {
  const controller = new AbortController()
  let cancelled = false

  void (async () => {
    let response: Response
    try {
      response = await authFetch(
        `/courses/${encodeURIComponent(courseId)}/strategy-documents/revise`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: payload.message,
            history: payload.history.map(({ role, content }) => ({ role, content })),
            review_plan: payload.reviewPlan,
            course_prompt: payload.coursePrompt,
          }),
          signal: controller.signal,
        },
      )
    } catch (error) {
      if (!cancelled) handlers.onError(error instanceof Error ? error.message : '无法连接策略修订接口。')
      return
    }
    if (!response.ok || !response.body) {
      if (!cancelled) handlers.onError(`策略修订接口返回异常（HTTP ${response.status}）。`)
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let separatorIndex = buffer.indexOf('\n\n')
        while (separatorIndex >= 0) {
          const rawEvent = buffer.slice(0, separatorIndex)
          buffer = buffer.slice(separatorIndex + 2)
          parseAgentSseEvent(rawEvent, {
            onToken: handlers.onToken,
            onDone: (result) => handlers.onDone(result as unknown as StrategyRevisionStreamDone),
            onError: handlers.onError,
          })
          separatorIndex = buffer.indexOf('\n\n')
        }
      }
      if (buffer.trim()) {
        parseAgentSseEvent(buffer, {
          onToken: handlers.onToken,
          onDone: (result) => handlers.onDone(result as unknown as StrategyRevisionStreamDone),
          onError: handlers.onError,
        })
      }
    } catch (error) {
      if (!cancelled) handlers.onError(error instanceof Error ? error.message : '读取策略修订流失败。')
    }
  })()

  return {
    cancel: () => {
      cancelled = true
      controller.abort()
    },
  }
}

export function dismissCourseAdjustmentProposal(courseId: string, proposalId: string) {
  return request<AdjustmentProposal>(
    `/courses/${encodeURIComponent(courseId)}/adjustment-proposals/${encodeURIComponent(proposalId)}/dismiss`,
    { method: 'POST' },
  )
}

export function adjustCoursePlan(courseId: string, payload: PlanParamsAdjustRequest) {
  return request<PlanParamsAdjustResponse>(
    `/courses/${encodeURIComponent(courseId)}/plan/adjust`,
    {
      method: 'POST',
      body: JSON.stringify({
        exam_date: payload.examDate,
        days: payload.days,
        daily_hours: payload.dailyHours,
      }),
    },
  )
}

export function listMcpServers() {
  return request<McpServer[]>('/mcp/servers')
}

export function saveMcpServer(payload: {
  id?: string
  name: string
  endpoint: string
  transport: McpServer['transport']
  command: string
  args: string[]
  allowedTools: string[]
}) {
  return request<McpServer>('/mcp/servers', {
    method: 'PUT',
    body: JSON.stringify({
      id: payload.id ?? '',
      name: payload.name,
      endpoint: payload.endpoint,
      transport: payload.transport,
      command: payload.command,
      args: payload.args,
      allowed_tools: payload.allowedTools,
    }),
  })
}

export function discoverMcpServer(serverId: string) {
  return request<McpServer>(`/mcp/servers/${encodeURIComponent(serverId)}/discover`, { method: 'POST' })
}

export function getBilibiliCredentialStatus() {
  return request<BilibiliCredentialStatus>('/mcp/bilibili/credentials')
}

export function verifyBilibiliCredentials() {
  // 后端 MCP 子进程超时为 120s（npx 首次拉起较慢），前端 135s 兜底
  return request<BilibiliCredentialVerifyResult>('/mcp/bilibili/credentials/verify', undefined, 135_000)
}

export function saveBilibiliCredentials(payload: { sessdata: string; biliJct: string; dedeuserid: string }) {
  return request<BilibiliCredentialStatus>('/mcp/bilibili/credentials', {
    method: 'PUT',
    body: JSON.stringify({
      sessdata: payload.sessdata,
      bili_jct: payload.biliJct,
      dedeuserid: payload.dedeuserid,
    }),
  })
}

export function clearBilibiliCredentials() {
  return request<BilibiliCredentialStatus>('/mcp/bilibili/credentials', { method: 'DELETE' })
}

export function submitCourseExternalSource(courseId: string, payload: {
  url: string
  mcpServerId: string
  toolName: string
  sourceType: ExternalSource['sourceType']
}) {
  return request<ExternalSource>(`/courses/${encodeURIComponent(courseId)}/external-sources`, {
    method: 'POST',
    body: JSON.stringify({
      url: payload.url,
      mcp_server_id: payload.mcpServerId,
      tool_name: payload.toolName,
      source_type: payload.sourceType,
    }),
  })
}

export function getCourseExternalSource(courseId: string, sourceId: string) {
  return request<ExternalSource>(
    `/courses/${encodeURIComponent(courseId)}/external-sources/${encodeURIComponent(sourceId)}`,
  )
}

export function approveCourseExternalSource(courseId: string, sourceId: string) {
  return request<{ source: ExternalSource; workspace: StudyWorkspace }>(
    `/courses/${encodeURIComponent(courseId)}/external-sources/${encodeURIComponent(sourceId)}/approve`,
    { method: 'POST' },
  )
}

export function dismissCourseExternalSource(courseId: string, sourceId: string) {
  return request<ExternalSource>(
    `/courses/${encodeURIComponent(courseId)}/external-sources/${encodeURIComponent(sourceId)}/dismiss`,
    { method: 'POST' },
  )
}

export async function deleteCourseWrongAnswer(courseId: string, wrongAnswerId: string) {
  const response = await request<WrongAnswerArchiveApiResponse>(
    `/courses/${encodeURIComponent(courseId)}/wrong-answers/${encodeURIComponent(wrongAnswerId)}`,
    {
      method: 'DELETE',
    },
  )
  return {
    workspace: response.workspace,
    archiveItem: toArchiveItem(response.archive_item),
  }
}

export async function listArchiveItems() {
  const archiveItems = await request<ArchiveItemApiResponse[]>('/archive')
  return archiveItems.map(toArchiveItem)
}

export async function permanentlyDeleteArchiveItem(archiveId: string) {
  const response = await request<{ deleted: boolean; archive_items: ArchiveItemApiResponse[] }>(
    `/archive/${encodeURIComponent(archiveId)}`,
    { method: 'DELETE' },
  )
  return { deleted: response.deleted, archiveItems: response.archive_items.map(toArchiveItem) }
}

export async function restoreArchiveItem(archiveId: string) {
  const response = await request<RestoreArchiveApiResponse>(`/archive/${encodeURIComponent(archiveId)}/restore`, {
    method: 'POST',
  })
  return {
    itemType: response.item_type,
    course: response.course ? toCourse(response.course) : undefined,
    workspace: response.workspace,
    archiveItems: response.archive_items.map(toArchiveItem),
  }
}

export function toRuntimeModelProfile(
  runtimeModel: RuntimeModel,
): ModelProfile {
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
}

export type GlossaryTermApiResponse = {
  id: string
  term: string
  matchKey?: string
  aliases: string[]
  oneLiner: string
  article: string
  examTips: string[]
  pitfalls: string[]
  knowledgePointId?: string
  relatedKnowledgePointIds: string[]
  moduleId?: string
  importance: 'core' | 'extended'
  status: 'draft' | 'active' | 'inactive'
  origin: 'curator' | 'manual'
  updatedAt?: string
}

export type GlossaryStatusApiResponse = {
  courseId: string
  status: 'idle' | 'generating' | 'ready' | 'failed'
  termsTotal: number
  termsActive: number
  candidatesTotal?: number
  termsCompleted?: number
  phase?: 'idle' | 'scanning' | 'composing' | 'finalizing' | 'ready' | 'failed'
  startedAt?: string
  progressUpdatedAt?: string
  lastError: string
  lastRefreshedAt: string
}

export function toGlossaryTerm(response: GlossaryTermApiResponse): GlossaryTerm {
  return {
    id: response.id,
    term: response.term,
    aliases: response.aliases ?? [],
    oneLiner: response.oneLiner ?? '',
    article: response.article ?? '',
    examTips: response.examTips ?? [],
    pitfalls: response.pitfalls ?? [],
    knowledgePointId: response.knowledgePointId || undefined,
    relatedKnowledgePointIds: response.relatedKnowledgePointIds ?? [],
    moduleId: response.moduleId || undefined,
    importance: response.importance ?? 'core',
    status: response.status ?? 'active',
    origin: response.origin ?? 'curator',
    updatedAt: response.updatedAt ?? '',
  }
}

export function toGlossaryStatus(courseId: string, response: GlossaryStatusApiResponse): GlossaryStatus {
  return {
    courseId,
    status: response.status ?? 'idle',
    termsTotal: response.termsTotal ?? 0,
    termsActive: response.termsActive ?? 0,
    candidatesTotal: response.candidatesTotal ?? 0,
    termsCompleted: response.termsCompleted ?? 0,
    phase: response.phase ?? (response.status === 'generating' ? 'scanning' : response.status ?? 'idle'),
    startedAt: response.startedAt ?? '',
    progressUpdatedAt: response.progressUpdatedAt ?? '',
    lastError: response.lastError ?? '',
    lastRefreshedAt: response.lastRefreshedAt ?? '',
  }
}

export async function getCourseGlossary(courseId: string): Promise<GlossaryResponse> {
  const response = await request<{ courseId: string; terms: GlossaryTermApiResponse[]; status: GlossaryStatusApiResponse }>(
    `/courses/${encodeURIComponent(courseId)}/glossary`,
  )
  return {
    courseId,
    terms: (response.terms ?? []).map(toGlossaryTerm),
    status: toGlossaryStatus(courseId, response.status ?? ({ courseId: response.courseId } as GlossaryStatusApiResponse)),
  }
}

export async function getCourseGlossaryStatus(courseId: string): Promise<GlossaryStatus> {
  const response = await request<GlossaryStatusApiResponse>(
    `/courses/${encodeURIComponent(courseId)}/glossary/status`,
  )
  return toGlossaryStatus(courseId, response)
}

export async function refreshCourseGlossary(courseId: string, force = false): Promise<{ jobId: string; courseId: string }> {
  return request(`/courses/${encodeURIComponent(courseId)}/glossary/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force }),
  })
}

export async function updateGlossaryTerm(
  courseId: string,
  termId: string,
  fields: Partial<Pick<GlossaryTerm, 'term' | 'aliases' | 'oneLiner' | 'article' | 'examTips' | 'pitfalls' | 'importance' | 'status'>>,
): Promise<GlossaryTerm> {
  const payload: Record<string, unknown> = {}
  if (fields.term !== undefined) payload.term = fields.term
  if (fields.aliases !== undefined) payload.aliases = fields.aliases
  if (fields.oneLiner !== undefined) payload.one_liner = fields.oneLiner
  if (fields.article !== undefined) payload.article = fields.article
  if (fields.examTips !== undefined) payload.exam_tips = fields.examTips
  if (fields.pitfalls !== undefined) payload.pitfalls = fields.pitfalls
  if (fields.importance !== undefined) payload.importance = fields.importance
  if (fields.status !== undefined) payload.status = fields.status
  const response = await request<{ term: GlossaryTermApiResponse }>(
    `/courses/${encodeURIComponent(courseId)}/glossary/terms/${encodeURIComponent(termId)}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  )
  return toGlossaryTerm(response.term)
}

export async function deleteGlossaryTerm(courseId: string, termId: string): Promise<GlossaryResponse> {
  const response = await request<{ courseId: string; terms: GlossaryTermApiResponse[]; status: GlossaryStatusApiResponse }>(
    `/courses/${encodeURIComponent(courseId)}/glossary/terms/${encodeURIComponent(termId)}`,
    { method: 'DELETE' },
  )
  return {
    courseId,
    terms: (response.terms ?? []).map(toGlossaryTerm),
    status: toGlossaryStatus(courseId, response.status ?? ({ courseId: response.courseId } as GlossaryStatusApiResponse)),
  }
}
