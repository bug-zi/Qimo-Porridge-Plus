import {
  type CSSProperties,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  ArrowUp,
  BookOpen,
  Check,
  ChevronDown,
  Clock3,
  FileText,
  GraduationCap,
  LoaderCircle,
  Moon,
  PanelRightOpen,
  Plus,
  Search,
  Sparkles,
  Sun,
  Trash2,
  X,
} from 'lucide-react'
import {
  adjustCoursePlan,
  applyCourseAdjustmentProposal,
  askCourseAgent,
  streamCourseAgent,
  type AgentStreamHandle,
  approveStrategyDocumentsInBackground,
  clearCourseMockResult,
  clearCoursePracticeAnswer,
  createCourse,
  deleteCourse,
  deleteCourseMaterial,
  deleteCourseTimeLog,
  deleteCourseWrongAnswer,
  dismissCourseAdjustmentProposal,
  generateStrategyDocuments,
  getAgentJob,
  getCourseWorkspace,
  getStrategyDocuments,
  getRuntimeModel,
  listArchiveItems,
  listCourses,
  recordCourseTimeLog,
  rescanCourseMaterials,
  restoreArchiveItem,
  searchCourse,
  saveCoursePrompt,
  saveCourseSetup,
  submitCourseDiagnostic,
  submitCourseMockAnswers,
  submitCoursePracticeAnswer,
  submitCourseWrongAnswerRetry,
  toRuntimeModelProfile,
  updateCourseWorkspace,
  flushCourseWorkspaceNote,
  uploadCourseMaterials,
} from './apiClient'
import { AiCompanion } from './components/AiCompanion'
import { MainNavigation } from './components/Sidebar'
import { OptionWheel } from './components/OptionWheel'
import { ModuleView } from './components/ModuleView'
import { SelectionToNoteToolbar } from './components/SelectionToNoteToolbar'
import { TopbarCourseTimer } from './components/TopbarCourseTimer'
import { CourseTimerProvider } from './hooks/useCourseTimer'
import { GlossaryProvider } from './hooks/useGlossary'
import { AUTH_EXPIRED_EVENT, getStoredUser, hasSession, logout, type AuthUser } from './auth'
import { LoginPage } from './components/LoginPage'
import { isDemoMode } from './apiClient'
import { useSpecularButtons } from './hooks/useSpecularButtons'
import { buildCourseTimeline, summarizeTimeline, COURSE_CATEGORY_TABS, type CourseTimelineCategory } from './utils/courseTimeline'
import type {
  AdjustmentProposal,
  AgentJob,
  ArchiveItem,
  Course,
  LearningModule,
  MockAnswer,
  ModelProfile,
  PlanParamsAdjustRequest,
  PlanTask,
  SearchResult,
  StreamingMessage,
  StudyWorkspace,
  UiFont,
  UiFontSize,
  WrongAnswer,
} from './types'
import { createFallbackTasks } from './data/demoData'
import './App.css'

const defaultModelProfile: ModelProfile = {
  provider: 'custom',
  baseUrl: '',
  model: 'gpt-5.5',
  apiKey: '',
  hasApiKey: false,
  supportsVision: true,
  status: 'unconfigured',
  statusMessage: '正在读取本机模型配置',
}

type NewCourseForm = {
  name: string
  examDate: string
  targetScore: string
  dailyHours: string
}

type StrategyGenerationJobState = {
  courseId: string
  job: AgentJob
  startedAtMs: number
  elapsedSeconds: number
}

const initialNewCourseForm: NewCourseForm = {
  name: '',
  examDate: '',
  targetScore: '80',
  dailyHours: '2',
}

const uiFontStorageKey = 'final-congee-ui-font'
const uiFontSizeStorageKey = 'final-congee-ui-font-size'
const activeCourseStorageKey = 'final-congee-active-course'
const aiPanelMinWidth = 280
const aiPanelMaxWidth = 620
const aiPanelDockedBreakpoint = 1180

const uiFontIds: UiFont[] = [
  'system',
  'lakeus-night-writing',
  'maple-mono-nf-cn',
  'honglei-banshu',
  'liyu-xingkai',
  'nanxi-ink-song',
  'lxgw-wenkai',
  'xuanzongti',
  'slidexiaxing',
  'slideyouran',
]

const uiFontSizeOptions: UiFontSize[] = [90, 95, 100, 105, 110, 115]

function readInitialUiFont(): UiFont {
  if (typeof window === 'undefined') return 'system'
  try {
    const storedFont = window.localStorage.getItem(uiFontStorageKey)
    return storedFont && uiFontIds.includes(storedFont as UiFont) ? (storedFont as UiFont) : 'system'
  } catch {
    return 'system'
  }
}

function readInitialUiFontSize(): UiFontSize {
  if (typeof window === 'undefined') return 100
  try {
    const storedFontSize = Number(window.localStorage.getItem(uiFontSizeStorageKey))
    return uiFontSizeOptions.includes(storedFontSize as UiFontSize) ? (storedFontSize as UiFontSize) : 100
  } catch {
    return 100
  }
}

function getAiPanelMaxWidth() {
  if (typeof window === 'undefined') return 340
  const navWidth = window.innerWidth <= 1450 ? 78 : 92
  const mainMinWidth = window.innerWidth <= 1450 ? 520 : 560
  const availableWidth = window.innerWidth - navWidth - mainMinWidth
  return Math.max(aiPanelMinWidth, Math.min(aiPanelMaxWidth, availableWidth))
}

function clampAiPanelWidth(width: number) {
  return Math.min(getAiPanelMaxWidth(), Math.max(aiPanelMinWidth, Math.round(width)))
}

function getAiPanelResizeWidth(clientX: number) {
  if (typeof window === 'undefined') return 340
  return clampAiPanelWidth(window.innerWidth - clientX)
}

function mergeCourseList(...courseGroups: Course[][]) {
  const coursesById = new Map<string, Course>()
  courseGroups.flat().forEach((course) => {
    if (!coursesById.has(course.id)) {
      coursesById.set(course.id, course)
    }
  })
  return Array.from(coursesById.values())
}

function QuickBackToTopButton() {
  function handleBackToTop() {
    window.scrollTo({ top: 0, behavior: 'smooth' })
    document.querySelector('.main-area')?.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <button
      className="icon-button desktop-only"
      type="button"
      title="快速返回顶部"
      aria-label="快速返回顶部"
      onClick={handleBackToTop}
    >
      <ArrowUp size={18} />
    </button>
  )
}

type CourseSwitcherProps = {
  courses: Course[]
  activeCourse: Course
  isOpen: boolean
  menuRef: RefObject<HTMLDivElement | null>
  onToggle: () => void
  onSelectCourse: (course: Course) => void
  onDeleteCourse: (course: Course) => void
  onNewCourse: () => void
}

function CourseSwitcher({
  courses,
  activeCourse,
  isOpen,
  menuRef,
  onToggle,
  onSelectCourse,
  onDeleteCourse,
  onNewCourse,
}: CourseSwitcherProps) {
  const [focusedId, setFocusedId] = useState(activeCourse.id)
  // 当前查看的课程分类：默认「备考」，每次打开切换器回到「备考」。
  const [activeTab, setActiveTab] = useState<CourseTimelineCategory>('active')

  // 外部 active 变化时，滚轮居中回到当前课程。
  useEffect(() => {
    setFocusedId(activeCourse.id)
  }, [activeCourse.id])

  // 每次打开切换器默认显示「备考」课程。
  useEffect(() => {
    if (isOpen) setActiveTab('active')
  }, [isOpen])

  // 按考试时间分成「备考 / 历史」两类并排序：备考在前（升序），历史在后（降序）。
  const timeline = useMemo(() => buildCourseTimeline(courses), [courses])
  const categoryCounts = useMemo(() => summarizeTimeline(timeline), [timeline])
  // 仅展示当前选中分类的课程。
  const ordered = useMemo(
    () => timeline.filter((entry) => entry.category === activeTab).map((entry) => entry.course),
    [timeline, activeTab],
  )

  // 切换分类或删除当前预览项后，焦点落回 active 课程或该分类首门，避免滚轮指向不存在的项。
  useEffect(() => {
    if (ordered.length === 0) return
    if (ordered.some((c) => c.id === focusedId)) return
    setFocusedId(ordered.some((c) => c.id === activeCourse.id) ? activeCourse.id : ordered[0].id)
  }, [ordered, focusedId, activeCourse.id])

  const safeIndex = Math.max(0, ordered.findIndex((c) => c.id === focusedId))
  const focused = ordered[safeIndex]

  return (
    <div className={`course-switcher ${isOpen ? 'is-open' : ''}`} ref={menuRef}>
      <button
        className="course-switcher-trigger"
        type="button"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        onClick={onToggle}
      >
        <GraduationCap size={16} />
        <span className="course-switcher-label">查看课程</span>
        <strong>{activeCourse.name}</strong>
        <ChevronDown size={15} />
      </button>

      {isOpen && (
        <section className="course-switcher-menu" role="menu" aria-label="课程列表">
          {timeline.length === 0 ? (
            <div className="course-switcher-empty">还没有课程，添加一门开始吧</div>
          ) : (
            <>
              <div className="course-category-tabs" role="tablist" aria-label="课程分类">
                {COURSE_CATEGORY_TABS.map((tab) => {
                  const count = categoryCounts[tab.key]
                  const isActive = activeTab === tab.key
                  return (
                    <button
                      key={tab.key}
                      type="button"
                      role="tab"
                      aria-selected={isActive}
                      data-status={tab.key}
                      className={`course-category-tab${isActive ? ' is-active' : ''}`}
                      onClick={() => setActiveTab(tab.key)}
                      disabled={count === 0 && !isActive}
                    >
                      <span>{tab.label}</span>
                      <small>{count}</small>
                    </button>
                  )
                })}
              </div>

              {ordered.length === 0 ? (
                <div className="course-switcher-empty">
                  {activeTab === 'active' ? '还没有备考课程' : '还没有历史课程'}
                </div>
              ) : (
                <>
                  <div className="course-switcher-wheel-area">
                    <OptionWheel
                      className="course-switcher-wheel"
                      items={ordered.map((c) => c.name)}
                      index={safeIndex}
                      onChange={(i) => setFocusedId(ordered[i].id)}
                      onActivate={() => focused && onSelectCourse(focused)}
                      fontSize={1.25}
                      centered
                      ariaLabel="课程选择滚轮"
                    />
                  </div>

                  {focused && (
                    <div className="course-switcher-focus">
                      <div className="course-switcher-focus-meta">
                        <div className="course-switcher-focus-title-row">
                          <strong>{focused.name}</strong>
                        </div>
                        <small>{focused.examDate} · 目标 {focused.targetScore} 分 · 每日 {focused.dailyHours}h</small>
                      </div>
                      <div className="course-switcher-focus-actions">
                        <button
                          className="primary-button course-switcher-confirm"
                          type="button"
                          onClick={() => onSelectCourse(focused)}
                        >
                          <Check size={14} /> 切换到此课程
                        </button>
                        <button
                          className="course-switcher-delete"
                          type="button"
                          title={`删除 ${focused.name}`}
                          aria-label={`删除 ${focused.name}`}
                          onClick={() => onDeleteCourse(focused)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </>
          )}

          <button className="course-switcher-add" type="button" onClick={onNewCourse}>
            <Plus size={15} /> 添加课程
          </button>
        </section>
      )}
    </div>
  )
}

function createLocalCourseWorkspace(course: Course): StudyWorkspace {
  return {
    course,
    assessmentProfile: {
      summary: `${course.name}课程已创建。先按考试范围、课堂资料和高频题型梳理复习重点。`,
      questionTypes: ['待整理'],
    },
    diagnostic: {
      estimatedScore: '未摸底',
      message: '新课程已加入，完成主线任务后再根据学习情况调整优先级。',
    },
    knowledgePoints: [
      {
        id: `${course.id}-scope`,
        name: '考试范围梳理',
        mastery: 20,
        weight: 30,
        summary: '先明确考试章节、题型和不考范围。',
        source: '课程设置',
      },
      {
        id: `${course.id}-materials`,
        name: '资料重点提炼',
        mastery: 18,
        weight: 35,
        summary: '把课件、练习和真题中的高频结论整理出来。',
        source: '课程资料库',
      },
      {
        id: `${course.id}-exam`,
        name: '真题节奏训练',
        mastery: 12,
        weight: 35,
        summary: '用限时练习检查知识点调用速度和失分点。',
        source: '模拟演练',
      },
    ],
    tasks: createFallbackTasks(course).map((task, index) => ({
      ...task,
      courseId: course.id,
      day: index + 1,
      order: index + 1,
    })),
    practiceQuestions: [],
    mockQuestions: [],
    materials: [],
    wrongAnswers: [],
    note: `## ${course.name}考前笔记\n\n- 先整理考试范围和重点章节。\n- 把课堂例题、平时作业和真题中的高频题型列出来。`,
    messages: [
      {
        id: `${course.id}-welcome`,
        role: 'assistant',
        content: `${course.name}课程已加入。我会先用基础主线承接复习，后续可围绕资料和错题继续细化。`,
        createdAt: '刚刚',
      },
    ],
    generatedAt: new Date().toISOString(),
    generationMode: 'fallback',
  }
}

function App() {
  // 认证门（阶段1）：演示模式跳过；有会话才挂工作台，refresh 失效时回到登录页
  const [authUser, setAuthUser] = useState<AuthUser | null>(() => (isDemoMode ? { id: 'demo', email: '', displayName: '演示', role: 'user' } : getStoredUser()))
  const isAuthed = isDemoMode || (hasSession() && authUser !== null)

  useEffect(() => {
    if (isDemoMode) return
    function handleAuthExpired() {
      setAuthUser(null)
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired)
  }, [])

  async function handleLogout() {
    await logout()
    setAuthUser(null)
    setWorkspace(null)
    setCourses([])
    setCourseWorkspaces({})
    setActiveCourseId('')
  }

  const [workspace, setWorkspace] = useState<StudyWorkspace | null>(null)
  const [courses, setCourses] = useState<Course[]>([])
  const [archiveItems, setArchiveItems] = useState<ArchiveItem[]>([])
  const [activeCourseId, setActiveCourseId] = useState('')
  const [courseWorkspaces, setCourseWorkspaces] = useState<Record<string, StudyWorkspace>>({})
  const [activeModule, setActiveModule] = useState<LearningModule>('overview')
  const [activeStudyTaskId, setActiveStudyTaskId] = useState<string | null>(null)
  const [streamingMessage, setStreamingMessage] = useState<StreamingMessage | null>(null)
  const streamHandleRef = useRef<AgentStreamHandle | null>(null)
  // token 到达往往远快于帧率：先攒进缓冲，rAF 时一次性合入 state，把流式重渲染压到每帧至多一次
  const tokenBufferRef = useRef('')
  const tokenFlushRef = useRef<number | null>(null)

  const flushStreamingTokens = useCallback(() => {
    tokenFlushRef.current = null
    const chunk = tokenBufferRef.current
    if (!chunk) return
    tokenBufferRef.current = ''
    setStreamingMessage((current) => (current ? { ...current, content: current.content + chunk } : current))
  }, [])

  const scheduleStreamingFlush = useCallback(() => {
    if (tokenFlushRef.current !== null) return
    tokenFlushRef.current = requestAnimationFrame(flushStreamingTokens)
  }, [flushStreamingTokens])

  /** 丢弃未刷新的缓冲 token：新流开始 / 流结束时调用，防止上一轮残留串扰下一轮。 */
  const cancelStreamingFlush = useCallback(() => {
    if (tokenFlushRef.current !== null) {
      cancelAnimationFrame(tokenFlushRef.current)
      tokenFlushRef.current = null
    }
    tokenBufferRef.current = ''
  }, [])
  const [theme, setTheme] = useState<'light' | 'dark'>('light')
  const [uiFont, setUiFont] = useState<UiFont>(readInitialUiFont)
  const [uiFontSize, setUiFontSize] = useState<UiFontSize>(readInitialUiFontSize)
  const [modelProfile, setModelProfile] = useState<ModelProfile>(defaultModelProfile)
  const [proposal, setProposal] = useState<AdjustmentProposal | null>(null)
  const [isCourseMenuOpen, setIsCourseMenuOpen] = useState(false)
  const [isAiOpen, setIsAiOpen] = useState(false)
  const [isAiCollapsed, setIsAiCollapsed] = useState(false)
  const [aiPanelWidth, setAiPanelWidth] = useState<number | null>(null)
  const [isAiResizing, setIsAiResizing] = useState(false)
  const [isMaterialPreviewOpen, setIsMaterialPreviewOpen] = useState(false)
  const [materialPreviewPath, setMaterialPreviewPath] = useState<string | null>(null)
  const [isNewCourseOpen, setIsNewCourseOpen] = useState(false)
  const [newCourseForm, setNewCourseForm] = useState<NewCourseForm>(initialNewCourseForm)
  const [newCourseError, setNewCourseError] = useState('')
  const [isCreatingCourse, setIsCreatingCourse] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searchError, setSearchError] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [hasSearched, setHasSearched] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [diagnosticReviewAnswers, setDiagnosticReviewAnswers] = useState<Record<string, number> | null>(null)
  const [strategyGenerationJob, setStrategyGenerationJob] = useState<StrategyGenerationJobState | null>(null)
  const courseMenuRef = useRef<HTMLDivElement | null>(null)
  const noteSaveTimer = useRef<number | undefined>(undefined)
  // 最近一次尚停留在防抖定时器里、未真正发出的笔记；供 beforeunload 兜底 flush。
  const pendingNoteRef = useRef<{ courseId: string; note: string } | null>(null)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    if (!strategyGenerationJob || !['queued', 'running'].includes(strategyGenerationJob.job.status)) return
    const timer = window.setInterval(() => {
      setStrategyGenerationJob((current) => current
        ? { ...current, elapsedSeconds: Math.floor((Date.now() - current.startedAtMs) / 1000) }
        : current)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [strategyGenerationJob?.job.id, strategyGenerationJob?.job.status])

  useEffect(() => {
    if (!strategyGenerationJob || !['queued', 'running'].includes(strategyGenerationJob.job.status)) return
    let isCancelled = false
    async function pollGenerationJob() {
      if (!strategyGenerationJob) return
      try {
        const job = await getAgentJob(strategyGenerationJob.job.id)
        if (isCancelled) return
        setStrategyGenerationJob((current) => current ? { ...current, job } : current)
        if (job.status === 'running') {
          const previewWorkspace = await getCourseWorkspace(strategyGenerationJob.courseId)
          if (isCancelled) return
          setCourseWorkspaces((current) => ({ ...current, [previewWorkspace.course.id]: previewWorkspace }))
          setCourses((current) => mergeCourseList([previewWorkspace.course], current))
        }
        if (job.status === 'completed') {
          const refreshedWorkspace = await getCourseWorkspace(strategyGenerationJob.courseId)
          if (isCancelled) return
          setCourseWorkspaces((current) => ({ ...current, [refreshedWorkspace.course.id]: refreshedWorkspace }))
          setCourses((current) => mergeCourseList([refreshedWorkspace.course], current))
          setActiveCourseId(refreshedWorkspace.course.id)
          setActiveModule('plan')
          window.setTimeout(() => {
            setStrategyGenerationJob((current) => current?.job.id === job.id ? null : current)
          }, 8000)
        } else if (job.status === 'failed') {
          const failedWorkspace = await getCourseWorkspace(strategyGenerationJob.courseId)
          if (isCancelled) return
          setCourseWorkspaces((current) => ({ ...current, [failedWorkspace.course.id]: failedWorkspace }))
          setCourses((current) => mergeCourseList([failedWorkspace.course], current))
          setActiveModule('materials')
        }
      } catch (error) {
        if (isCancelled) return
        setStrategyGenerationJob((current) => current
          ? { ...current, job: { ...current.job, status: 'failed', error: error instanceof Error ? error.message : '后台任务状态读取失败' } }
          : current)
      }
    }
    void pollGenerationJob()
    const timer = window.setInterval(() => void pollGenerationJob(), 1800)
    return () => {
      isCancelled = true
      window.clearInterval(timer)
    }
  }, [strategyGenerationJob?.job.id, strategyGenerationJob?.job.status])

  useEffect(() => {
    document.documentElement.dataset.appFont = uiFont
    try {
      window.localStorage.setItem(uiFontStorageKey, uiFont)
    } catch {
      // 当前会话仍会应用字体，存储失败时不打断界面。
    }
  }, [uiFont])

  useEffect(() => {
    document.documentElement.style.setProperty('--app-font-scale', String(uiFontSize / 100))
    try {
      window.localStorage.setItem(uiFontSizeStorageKey, String(uiFontSize))
    } catch {
      // 当前会话仍会应用字号，存储失败时不打断界面。
    }
  }, [uiFontSize])

  useEffect(() => {
    if (!activeCourseId) return
    try {
      window.localStorage.setItem(activeCourseStorageKey, activeCourseId)
    } catch {
      // 记不住上次课程时不影响当前会话。
    }
  }, [activeCourseId])

  useEffect(() => () => window.clearTimeout(noteSaveTimer.current), [])

  // 页面关闭/刷新前，把还没等到防抖触发就发出的笔记立即 flush，避免静默丢失。
  useEffect(() => {
    const handleBeforeUnload = () => {
      const pending = pendingNoteRef.current
      if (!pending) return
      window.clearTimeout(noteSaveTimer.current)
      noteSaveTimer.current = undefined
      pendingNoteRef.current = null
      flushCourseWorkspaceNote(pending.courseId, pending.note)
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [])

  // 为所有 .primary-button 注入 SpecularButton 风格的边框流光跟随效果
  useSpecularButtons()

  useEffect(() => {
    setSearchQuery('')
    setSearchResults([])
    setSearchError('')
    setHasSearched(false)
  }, [activeCourseId])

  useEffect(() => {
    function handleSearchShortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setSearchOpen(true)
      } else if (event.key === 'Escape') {
        setSearchOpen(false)
      }
    }

    window.addEventListener('keydown', handleSearchShortcut)
    return () => window.removeEventListener('keydown', handleSearchShortcut)
  }, [])

  useEffect(() => {
    function keepAiPanelWidthInRange() {
      if (window.innerWidth <= aiPanelDockedBreakpoint) return
      setAiPanelWidth((current) => (current === null ? current : clampAiPanelWidth(current)))
    }

    window.addEventListener('resize', keepAiPanelWidthInRange)
    return () => window.removeEventListener('resize', keepAiPanelWidthInRange)
  }, [])

  useEffect(() => {
    if (activeModule !== 'materials' || !activeCourseId) return
    let isActive = true
    const refreshStrategyDocuments = async () => {
      try {
        const strategyDocuments = await getStrategyDocuments(activeCourseId)
        if (!isActive) return
        setWorkspace((current) => current?.course.id === activeCourseId ? { ...current, strategyDocuments } : current)
        setCourseWorkspaces((current) => {
          const courseWorkspace = current[activeCourseId]
          return courseWorkspace
            ? { ...current, [activeCourseId]: { ...courseWorkspace, strategyDocuments } }
            : current
        })
      } catch {
        // 尚未生成策略文档时保持当前课程状态。
      }
    }
    void refreshStrategyDocuments()
    const timer = window.setInterval(refreshStrategyDocuments, 3000)
    return () => {
      isActive = false
      window.clearInterval(timer)
    }
  }, [activeCourseId, activeModule])

  useEffect(() => {
    if (!isCourseMenuOpen) return

    function closeCourseMenuOnOutsideClick(event: MouseEvent) {
      if (!courseMenuRef.current?.contains(event.target as Node)) {
        setIsCourseMenuOpen(false)
      }
    }

    function closeCourseMenuOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsCourseMenuOpen(false)
      }
    }

    document.addEventListener('mousedown', closeCourseMenuOnOutsideClick)
    window.addEventListener('keydown', closeCourseMenuOnEscape)
    return () => {
      document.removeEventListener('mousedown', closeCourseMenuOnOutsideClick)
      window.removeEventListener('keydown', closeCourseMenuOnEscape)
    }
  }, [isCourseMenuOpen])

  useEffect(() => {
    if (!isAuthed) return
    let isActive = true

    async function loadWorkspace() {
      try {
        const [runtimeModel, savedCourses, archivedItems] = await Promise.all([
          getRuntimeModel(),
          listCourses().catch(() => []),
          listArchiveItems().catch(() => []),
        ])
        let persistedCourseId: string | null = null
        try {
          persistedCourseId = window.localStorage.getItem(activeCourseStorageKey)
        } catch {
          persistedCourseId = null
        }
        const initialCourse = savedCourses.find((course) => course.id === persistedCourseId) ?? savedCourses[0]
        if (!initialCourse) throw new Error('尚未创建课程，请先在本机服务中创建课程。')
        const loadedWorkspace = await getCourseWorkspace(initialCourse.id)
        if (!isActive) return
        setWorkspace(loadedWorkspace)
        const visibleCourses = mergeCourseList([loadedWorkspace.course], savedCourses)
        setCourses(visibleCourses)
        setArchiveItems(archivedItems)
        setActiveCourseId(initialCourse.id)
        setModelProfile(toRuntimeModelProfile(runtimeModel))
      } catch (error) {
        if (!isActive) return
        setLoadError(error instanceof Error ? error.message : '课程学习空间加载失败')
      }
    }

    void loadWorkspace()
    return () => {
      isActive = false
    }
  }, [isAuthed])

  const activeCourse = courses.find((course) => course.id === activeCourseId)
    ?? (workspace?.course.id === activeCourseId ? workspace.course : undefined)
  const activeWorkspace = useMemo(() => {
    if (!workspace || !activeCourse) return null
    if (activeCourse.id === workspace.course.id) return workspace
    return courseWorkspaces[activeCourse.id] ?? createLocalCourseWorkspace(activeCourse)
  }, [activeCourse, courseWorkspaces, workspace])
  // 规划页需要全部课程的 workspace；把当前 live workspace 合进缓存，保证活动课程数据最新
  const planningWorkspaces = useMemo(() => {
    if (!workspace) return courseWorkspaces
    return { ...courseWorkspaces, [workspace.course.id]: workspace }
  }, [courseWorkspaces, workspace])
  const courseProgress = useMemo(() => {
    if (!activeWorkspace?.tasks.length) return activeWorkspace?.course.progress ?? 0
    return Math.round(
      activeWorkspace.tasks.reduce((sum, task) => sum + task.progress, 0) / activeWorkspace.tasks.length,
    )
  }, [activeWorkspace])
  const completedTasks = useMemo(
    () => activeWorkspace?.tasks.filter((task) => task.status === 'completed').length ?? 0,
    [activeWorkspace],
  )
  const appShellStyle = aiPanelWidth === null
    ? undefined
    : ({
        '--ai-panel-width': `${aiPanelWidth}px`,
      } as CSSProperties)

  function updateActiveWorkspace(updater: (current: StudyWorkspace) => StudyWorkspace) {
    if (!activeWorkspace) return
    if (workspace && activeWorkspace.course.id === workspace.course.id) {
      setWorkspace((current) => (current ? updater(current) : current))
      return
    }

    setCourseWorkspaces((current) => {
      const currentWorkspace = current[activeWorkspace.course.id] ?? activeWorkspace
      return {
        ...current,
        [activeWorkspace.course.id]: updater(currentWorkspace),
      }
    })
  }

  async function handleSelectCourse(course: Course) {
    setActiveCourseId(course.id)
    setDiagnosticReviewAnswers(null)
    setIsCourseMenuOpen(false)
    try {
      const loadedWorkspace = await getCourseWorkspace(course.id)
      if (workspace?.course.id === course.id) {
        setWorkspace(loadedWorkspace)
      } else {
        setCourseWorkspaces((current) => ({ ...current, [course.id]: loadedWorkspace }))
      }
    } catch {
      setCourseWorkspaces((current) => ({
        ...current,
        [course.id]: current[course.id] ?? createLocalCourseWorkspace(course),
      }))
    }
  }

  function updateWorkspaceTasks(tasks: PlanTask[]) {
    updateActiveWorkspace((current) => ({ ...current, tasks }))
    if (activeWorkspace) {
      // 乐观更新后用服务端返回对账：后端可能做 DAG 修复（任务顺延、schedulingWarnings）。
      void updateCourseWorkspace(activeWorkspace.course.id, { tasks })
        .then((reconciled) => {
          if (reconciled?.tasks) {
            updateActiveWorkspace((current) =>
              current.tasks === reconciled.tasks ? current : { ...current, ...reconciled },
            )
          }
        })
        .catch(() => undefined)
    }
  }

  const handleMaterialPreviewOpenChange = useCallback((isOpen: boolean) => {
    setIsMaterialPreviewOpen(isOpen)
  }, [])

  const handleAiPanelResizeStart = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    if (
      isAiCollapsed
      || isMaterialPreviewOpen
      || typeof window === 'undefined'
      || window.innerWidth <= aiPanelDockedBreakpoint
    ) {
      return
    }

    if (event.pointerType === 'mouse' && event.button !== 0) return

    event.preventDefault()
    setIsAiResizing(true)
    setAiPanelWidth(getAiPanelResizeWidth(event.clientX))

    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    function handlePointerMove(moveEvent: PointerEvent) {
      setAiPanelWidth(getAiPanelResizeWidth(moveEvent.clientX))
    }

    function stopResize() {
      setIsAiResizing(false)
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousUserSelect
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', stopResize)
      window.removeEventListener('pointercancel', stopResize)
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', stopResize)
    window.addEventListener('pointercancel', stopResize)
  }, [isAiCollapsed, isMaterialPreviewOpen])

  function changeActiveModule(module: LearningModule) {
    if (module !== 'overview') {
      setDiagnosticReviewAnswers(null)
    }
    setActiveModule(module)
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const query = searchQuery.trim()
    if (!activeWorkspace || !query || isSearching) return

    setIsSearching(true)
    setSearchError('')
    try {
      const results = await searchCourse(activeWorkspace.course.id, query)
      setSearchResults(results)
      setHasSearched(true)
    } catch (error) {
      setSearchResults([])
      setHasSearched(true)
      setSearchError(error instanceof Error ? error.message : '搜索失败，请稍后再试。')
    } finally {
      setIsSearching(false)
    }
  }

  function openSearchResult(result: SearchResult) {
    if (result.type === 'material' && result.source) {
      setMaterialPreviewPath(result.source)
    }
    changeActiveModule(result.module)
    setSearchOpen(false)
  }

  function updateWrongAnswers(wrongAnswers: WrongAnswer[]) {
    updateActiveWorkspace((current) => ({ ...current, wrongAnswers }))
    if (activeWorkspace) void updateCourseWorkspace(activeWorkspace.course.id, { wrongAnswers }).catch(() => undefined)
  }

  async function handleDeleteCourse(course: Course) {
    const confirmed = window.confirm(
      `确认删除「${course.name}」吗？删除后会先进入归档，7 天内可以恢复，超过 7 天会自动彻底删除。`,
    )
    if (!confirmed) return

    try {
      setIsCourseMenuOpen(false)
      const archiveItem = await deleteCourse(course.id)
      const remainingCourses = courses.filter((item) => item.id !== course.id)
      setCourses(remainingCourses)
      setArchiveItems((current) => [archiveItem, ...current.filter((item) => item.id !== archiveItem.id)])
      setCourseWorkspaces((current) => {
        const next = { ...current }
        delete next[course.id]
        return next
      })
      if (activeCourseId === course.id) {
        setActiveCourseId(remainingCourses[0]?.id ?? '')
        setActiveModule(remainingCourses.length ? 'overview' : 'archive')
      }
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '课程删除失败，请稍后再试。')
    }
  }

  async function handleDeleteWrongAnswer(wrongAnswer: WrongAnswer) {
    const confirmed = window.confirm(
      `确认删除这道错题吗？删除后会先进入归档，7 天内可以恢复，超过 7 天会自动彻底删除。`,
    )
    if (!confirmed) return

    if (!activeWorkspace) return

    try {
      const result = await deleteCourseWrongAnswer(activeWorkspace.course.id, wrongAnswer.id)
      updateActiveWorkspace(() => result.workspace)
      setArchiveItems((current) => [result.archiveItem, ...current.filter((item) => item.id !== result.archiveItem.id)])
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '错题删除失败，请稍后再试。')
    }
  }

  async function handleRestoreArchiveItem(archiveId: string) {
    try {
      const result = await restoreArchiveItem(archiveId)
      setArchiveItems(result.archiveItems)
      if (result.workspace) {
        const restoredWorkspace = result.workspace
        if (workspace?.course.id === restoredWorkspace.course.id) {
          setWorkspace(restoredWorkspace)
        } else {
          setCourseWorkspaces((current) => ({
            ...current,
            [restoredWorkspace.course.id]: restoredWorkspace,
          }))
        }
        if (result.itemType === 'course') {
          setCourses((current) => mergeCourseList(current, [result.workspace!.course]))
          setActiveCourseId(result.workspace.course.id)
          setActiveModule('overview')
        }
      }
      if (result.course) {
        setCourses((current) => mergeCourseList(current, [result.course!]))
        setActiveCourseId(result.course.id)
        setActiveModule('overview')
      }
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '恢复失败，请稍后再试。')
    }
  }

  function updateNote(note: string) {
    updateActiveWorkspace((current) => ({ ...current, note }))
    if (!activeWorkspace) return

    const courseId = activeWorkspace.course.id
    pendingNoteRef.current = { courseId, note }
    window.clearTimeout(noteSaveTimer.current)
    noteSaveTimer.current = window.setTimeout(() => {
      noteSaveTimer.current = undefined
      pendingNoteRef.current = null
      void updateCourseWorkspace(courseId, { note }).catch((error) => {
        window.alert(error instanceof Error ? `笔记保存失败：${error.message}` : '笔记保存失败，请重试。')
      })
    }, 550)
  }

  /** 把划词摘录追加到当前课程的复习笔记末尾（以 Markdown 引用块形式） */
  function appendNoteSnippet(snippet: string) {
    if (!activeWorkspace) return
    const normalized = snippet.replace(/\r\n?/g, '\n').trim()
    if (!normalized) return
    const blockquote = `> ${normalized.replace(/\n/g, '\n> ')}`
    const base = activeWorkspace.note.trimEnd()
    updateNote(`${base}${base ? '\n\n' : ''}${blockquote}\n`)
  }

  async function applyProposal() {
    if (!activeWorkspace || !proposal || proposal.status !== 'pending') return
    try {
      const result = await applyCourseAdjustmentProposal(activeWorkspace.course.id, proposal.id)
      updateActiveWorkspace(() => ({
        ...result.workspace,
        strategyDocuments: result.workspace.strategyDocuments ?? activeWorkspace.strategyDocuments,
      }))
      setProposal(result.proposal)
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '应用调整失败，请稍后再试。')
    }
  }

  async function dismissProposal() {
    if (!activeWorkspace || !proposal || proposal.status !== 'pending') return
    try {
      const result = await dismissCourseAdjustmentProposal(activeWorkspace.course.id, proposal.id)
      setProposal(result)
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '忽略调整失败，请稍后再试。')
    }
  }

  async function handleRecordTime(taskId: string | null, minutes: number, date?: string, note?: string) {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    try {
      const result = await recordCourseTimeLog(activeWorkspace.course.id, {
        taskId: taskId ?? undefined,
        minutes,
        date,
        note,
      })
      updateActiveWorkspace((current) => ({
        ...current,
        timeLog: [...(current.timeLog ?? []), ...(result.entry ? [result.entry] : [])],
        dailyProgress: result.dailyProgress,
      }))
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '记录时长失败，请稍后再试。')
      throw error
    }
  }

  async function handleRecordMinutes(courseId: string, _courseName: string, minutes: number) {
    try {
      const result = await recordCourseTimeLog(courseId, { taskId: undefined, minutes })
      if (activeWorkspace && activeWorkspace.course.id === courseId) {
        updateActiveWorkspace((current) => ({
          ...current,
          timeLog: [...(current.timeLog ?? []), ...(result.entry ? [result.entry] : [])],
          dailyProgress: result.dailyProgress,
        }))
      }
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '记录时长失败，请稍后再试。')
    }
  }

  async function handleDeleteTime(entryId: string) {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    try {
      const result = await deleteCourseTimeLog(activeWorkspace.course.id, entryId)
      updateActiveWorkspace((current) => ({
        ...current,
        timeLog: (current.timeLog ?? []).filter((entry) => entry.id !== entryId),
        dailyProgress: result.dailyProgress,
      }))
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '删除时长记录失败，请稍后再试。')
      throw error
    }
  }

  async function handleApplyPlanProposal(proposalId: string) {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    try {
      await applyCourseAdjustmentProposal(activeWorkspace.course.id, proposalId)
      const refreshedWorkspace = await getCourseWorkspace(activeWorkspace.course.id)
      updateActiveWorkspace(() => ({
        ...refreshedWorkspace,
        strategyDocuments: refreshedWorkspace.strategyDocuments ?? activeWorkspace.strategyDocuments,
        // 兜底：即使刷新结果里仍带这条已采纳的提案，也立刻从列表里移除，确保卡片即时消失
        pendingProposals: (refreshedWorkspace.pendingProposals ?? []).filter(
          (item) => item.id !== proposalId,
        ),
      }))
      // 采纳「重新编排」类提案时 dailyHours/days/examDate 会落地，需同步侧边栏课程列表
      setCourses((current) => mergeCourseList([refreshedWorkspace.course], current))
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '应用调整失败，请稍后再试。')
      throw error
    }
  }

  async function handleAdjustPlanParams(payload: PlanParamsAdjustRequest) {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    try {
      // 仅改考试日期 → 后端直接落地并刷新 review-plan.md（轻量分支，不产生卡片）；
      // 改天数/每日时间 → 后端生成「重新编排」提案，刷新后出现在 pendingProposals 待采纳。
      await adjustCoursePlan(activeWorkspace.course.id, payload)
      const refreshedWorkspace = await getCourseWorkspace(activeWorkspace.course.id)
      updateActiveWorkspace((current) => ({
        ...refreshedWorkspace,
        strategyDocuments: refreshedWorkspace.strategyDocuments ?? current.strategyDocuments,
      }))
      // 轻量分支会落地 examDate（侧边栏课程列表来自 SQLite listCourses，需同步刷新）
      setCourses((current) => mergeCourseList([refreshedWorkspace.course], current))
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '调整复习参数失败，请稍后再试。')
      throw error
    }
  }

  async function handleDismissPlanProposal(proposalId: string) {
    if (!activeWorkspace) return
    try {
      await dismissCourseAdjustmentProposal(activeWorkspace.course.id, proposalId)
      updateActiveWorkspace((current) => ({
        ...current,
        pendingProposals: (current.pendingProposals ?? []).filter((item) => item.id !== proposalId),
      }))
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '忽略调整失败，请稍后再试。')
      throw error
    }
  }

  async function handlePracticeAnswer(
    questionId: string,
    answerIndex: number,
    mode: '主线学习' | '刷题练习' = '刷题练习',
  ) {
    if (!activeWorkspace) {
      return {
        correct: false,
        explanation: '当前课程还没有生成定向练习题。',
        mastery: 0,
        generatedSimilarCount: 0,
      }
    }

    const result = await submitCoursePracticeAnswer(activeWorkspace.course.id, questionId, answerIndex, mode)
    updateActiveWorkspace(() => ({
      ...result.workspace,
      strategyDocuments: result.workspace.strategyDocuments ?? activeWorkspace.strategyDocuments,
    }))
    return result
  }

  async function handleWrongAnswerRetry(wrongAnswerId: string, answerIndex: number) {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    const result = await submitCourseWrongAnswerRetry(activeWorkspace.course.id, wrongAnswerId, answerIndex)
    updateActiveWorkspace(() => ({
      ...result.workspace,
      strategyDocuments: result.workspace.strategyDocuments ?? activeWorkspace.strategyDocuments,
    }))
    return result
  }

  async function handleMockSubmit(answers: Record<string, MockAnswer>) {
    if (!activeWorkspace) {
      return {
        score: 0,
        total: 0,
        results: [],
      }
    }

    const result = await submitCourseMockAnswers(activeWorkspace.course.id, answers)
    updateActiveWorkspace(() => ({
      ...result.workspace,
      strategyDocuments: result.workspace.strategyDocuments ?? activeWorkspace.strategyDocuments,
    }))
    return result
  }

  async function handleClearPracticeAnswer(questionId: string) {
    if (!activeWorkspace) return
    const refreshedWorkspace = await clearCoursePracticeAnswer(activeWorkspace.course.id, questionId)
    updateActiveWorkspace(() => ({
      ...refreshedWorkspace,
      strategyDocuments: refreshedWorkspace.strategyDocuments ?? activeWorkspace.strategyDocuments,
    }))
  }

  async function handleClearMockResult() {
    if (!activeWorkspace) return
    const refreshedWorkspace = await clearCourseMockResult(activeWorkspace.course.id)
    updateActiveWorkspace(() => ({
      ...refreshedWorkspace,
      strategyDocuments: refreshedWorkspace.strategyDocuments ?? activeWorkspace.strategyDocuments,
    }))
  }

  async function handleAgentMessage(message: string, mode: 'chat' | 'agent') {
    if (!activeWorkspace) return
    const workspaceSnapshot = activeWorkspace
    const activeStudyTask = activeStudyTaskId
      ? activeWorkspace.tasks.find((task) => task.id === activeStudyTaskId)
      : undefined
    const context = mode === 'agent' && activeStudyTask
      ? {
          activeModule,
          currentTaskId: activeStudyTask.id,
          currentTaskTitle: activeStudyTask.title,
          currentTaskDay: activeStudyTask.day,
          currentTaskOrder: activeStudyTask.order,
          currentTaskSource: activeStudyTask.source,
        }
      : undefined

    streamHandleRef.current?.cancel()
    cancelStreamingFlush()
    setStreamingMessage({ content: '', toolEvents: [] })

    try {
      await new Promise<void>((resolve, reject) => {
        streamHandleRef.current = streamCourseAgent(
          workspaceSnapshot.course.id,
          message,
          mode,
          {
            onToken: (text) => {
              tokenBufferRef.current += text
              scheduleStreamingFlush()
            },
            onToolStart: (event) =>
              setStreamingMessage((current) =>
                current
                  ? {
                      ...current,
                      toolEvents: [
                        ...current.toolEvents,
                        { step: event.step, name: event.name, label: event.label, status: 'running' },
                      ],
                    }
                  : current,
              ),
            onToolEnd: (event) =>
              setStreamingMessage((current) =>
                current
                  ? {
                      ...current,
                      toolEvents: current.toolEvents.map((toolEvent) =>
                        toolEvent.step === event.step &&
                        toolEvent.name === event.name &&
                        toolEvent.status === 'running'
                          ? { ...toolEvent, status: 'done', summary: event.summary }
                          : toolEvent,
                      ),
                    }
                  : current,
              ),
            onDone: (result) => {
              cancelStreamingFlush()
              setStreamingMessage(null)
              updateActiveWorkspace(() => ({
                ...result.workspace,
                strategyDocuments: result.workspace.strategyDocuments ?? workspaceSnapshot.strategyDocuments,
              }))
              if (result.proposal) setProposal(result.proposal)
              resolve()
            },
            onError: (errorMessage) => {
              cancelStreamingFlush()
              // 流式不可用（上游不支持 stream / 网络中断）→ 自动降级到非流式，保证用户拿到回复
              askCourseAgent(workspaceSnapshot.course.id, message, mode, context)
                .then((fallback) => {
                  updateActiveWorkspace(() => ({
                    ...fallback.workspace,
                    strategyDocuments: fallback.workspace.strategyDocuments ?? workspaceSnapshot.strategyDocuments,
                  }))
                  if (fallback.proposal) setProposal(fallback.proposal)
                  resolve()
                })
                .catch((error) => {
                  reject(error instanceof Error ? error : new Error(errorMessage))
                })
                .finally(() => setStreamingMessage(null))
            },
          },
          context,
        )
      })
    } catch (error) {
      cancelStreamingFlush()
      setStreamingMessage(null)
      throw error
    }
  }

  async function handleRescanMaterials() {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    const refreshedWorkspace = await rescanCourseMaterials(activeWorkspace.course.id)
    updateActiveWorkspace(() => ({
      ...refreshedWorkspace,
      strategyDocuments: refreshedWorkspace.strategyDocuments ?? activeWorkspace.strategyDocuments,
    }))
  }

  async function handleUploadMaterials(files: FileList) {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    const refreshedWorkspace = await uploadCourseMaterials(activeWorkspace.course.id, files)
    updateActiveWorkspace(() => ({
      ...refreshedWorkspace,
      strategyDocuments: refreshedWorkspace.strategyDocuments ?? activeWorkspace.strategyDocuments,
    }))
  }

  async function handleDeleteMaterial(material: { name: string; relativePath: string }) {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    const refreshedWorkspace = await deleteCourseMaterial(activeWorkspace.course.id, material.relativePath)
    updateActiveWorkspace(() => ({
      ...refreshedWorkspace,
      strategyDocuments: refreshedWorkspace.strategyDocuments ?? activeWorkspace.strategyDocuments,
    }))
  }

  async function handleSaveCourseSetup(payload: {
    courseName: string
    examDate: string
    targetScore: number
    targetText: string
    dailyHours: number
    days: number
    reviewCount: number
    examFormat: string
    remarks: string
  }) {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    setDiagnosticReviewAnswers(null)
    const refreshedWorkspace = await saveCourseSetup(activeWorkspace.course.id, payload)
    updateActiveWorkspace(() => refreshedWorkspace)
    setCourses((current) => mergeCourseList([refreshedWorkspace.course], current))
    setActiveCourseId(refreshedWorkspace.course.id)
  }

  async function handleSubmitDiagnostic(answers: Record<string, number>) {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    const refreshedWorkspace = await submitCourseDiagnostic(activeWorkspace.course.id, answers)
    updateActiveWorkspace(() => refreshedWorkspace)
    setCourses((current) => mergeCourseList([refreshedWorkspace.course], current))
    setActiveCourseId(refreshedWorkspace.course.id)
    setDiagnosticReviewAnswers(answers)
    setActiveModule('overview')
  }

  async function handleApproveStrategyDocuments(payload: {
    reviewPlan: string
    coursePrompt: string
    reviewPlanVersion: number
    coursePromptVersion: number
  }) {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    const queued = await approveStrategyDocumentsInBackground(activeWorkspace.course.id, payload)
    const now = Date.now()
    setStrategyGenerationJob({
      courseId: queued.courseId,
      startedAtMs: now,
      elapsedSeconds: 0,
      job: {
        id: queued.jobId,
        courseId: queued.courseId,
        jobType: 'approve_strategy_documents',
        status: 'queued',
        attempts: 0,
        maxAttempts: 2,
        error: '',
        result: {},
        createdAt: new Date(now).toISOString(),
        updatedAt: new Date(now).toISOString(),
      },
    })
    setActiveModule('plan')
  }

  async function handleRefreshWorkspace() {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    const refreshedWorkspace = await getCourseWorkspace(activeWorkspace.course.id)
    if (workspace && refreshedWorkspace.course.id === workspace.course.id) {
      setWorkspace(refreshedWorkspace)
    } else {
      setCourseWorkspaces((current) => ({ ...current, [refreshedWorkspace.course.id]: refreshedWorkspace }))
    }
    setCourses((current) => mergeCourseList([refreshedWorkspace.course], current))
    setActiveCourseId(refreshedWorkspace.course.id)
  }

  async function handleRepairStrategyGeneration() {
    if (!activeWorkspace?.strategyDocuments) throw new Error('当前课程没有可用于修复的策略文档。')
    const { reviewPlan, coursePrompt } = activeWorkspace.strategyDocuments
    await handleApproveStrategyDocuments({
      reviewPlan: reviewPlan.content,
      coursePrompt: coursePrompt.content,
      reviewPlanVersion: reviewPlan.version,
      coursePromptVersion: coursePrompt.version,
    })
  }

  async function handleGenerateStrategyDocuments() {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    const strategyDocuments = await generateStrategyDocuments(activeWorkspace.course.id)
    updateActiveWorkspace((current) => ({ ...current, strategyDocuments }))
  }

  async function handleSaveCoursePrompt(coursePrompt: string, version: number) {
    if (!activeWorkspace) throw new Error('当前课程尚未加载。')
    const strategyDocuments = await saveCoursePrompt(activeWorkspace.course.id, coursePrompt, version)
    updateActiveWorkspace((current) => ({ ...current, strategyDocuments }))
  }

  function updateNewCourseForm<K extends keyof NewCourseForm>(key: K, value: NewCourseForm[K]) {
    setNewCourseForm((current) => ({ ...current, [key]: value }))
    setNewCourseError('')
  }

  function closeNewCourseModal() {
    if (isCreatingCourse) return
    setIsNewCourseOpen(false)
    setNewCourseError('')
  }

  async function handleCreateCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const name = newCourseForm.name.trim()
    const examDate = newCourseForm.examDate
    const targetScore = Number(newCourseForm.targetScore)
    const dailyHours = Number(newCourseForm.dailyHours)

    if (!name || !examDate || !Number.isFinite(targetScore) || !Number.isFinite(dailyHours)) {
      setNewCourseError('请完整填写课程名称、考试日期、目标分数和每日时间。')
      return
    }

    if (!Number.isInteger(targetScore) || targetScore < 0 || targetScore > 100) {
      setNewCourseError('目标分数需要是 0 到 100 的整数。')
      return
    }

    if (dailyHours <= 0 || dailyHours > 24) {
      setNewCourseError('每日可用时间需要在 0 到 24 小时之间。')
      return
    }

    setIsCreatingCourse(true)
    try {
      const createdCourse = await createCourse({
        name,
        examDate,
        targetScore,
        dailyHours,
      })
      const createdWorkspace = await getCourseWorkspace(createdCourse.id)
      setCourses((current) => mergeCourseList(current, [createdCourse]))
      setCourseWorkspaces((current) => ({
        ...current,
        [createdCourse.id]: createdWorkspace,
      }))
      setActiveCourseId(createdCourse.id)
      setActiveModule('overview')
      setIsCourseMenuOpen(false)
      setIsNewCourseOpen(false)
      setNewCourseForm(initialNewCourseForm)
      setNewCourseError('')
    } catch (error) {
      setNewCourseError(error instanceof Error ? error.message : '课程创建失败，请稍后再试。')
    } finally {
      setIsCreatingCourse(false)
    }
  }

  if (!isAuthed) {
    return <LoginPage onAuthed={() => setAuthUser(getStoredUser())} />
  }

  if (loadError) {
    return (
      <div className="app-shell boot-shell">
        <main className="main-area">
          <section className="module-page empty-module">
            <BookOpen size={32} />
            <h1>课程学习空间暂未启动</h1>
            <p>{loadError}</p>
            <button className="primary-button" type="button" onClick={() => window.location.reload()}>
              重新连接本机服务
            </button>
          </section>
        </main>
      </div>
    )
  }

  if (!workspace || !activeCourse || !activeWorkspace) {
    return (
      <div className="app-shell boot-shell">
        <main className="main-area">
          <section className="module-page empty-module">
            <Sparkles size={32} />
            <h1>正在熬制期末粥</h1>
            <p>正在读取资料库、学习计划和 AI 模型配置。</p>
            <div className="boot-progress" aria-hidden="true"><span></span></div>
          </section>
        </main>
      </div>
    )
  }

  return (
    <GlossaryProvider courseId={activeCourseId}>
    <CourseTimerProvider onRecordMinutes={handleRecordMinutes}>
    <div
      className={`app-shell${isAiCollapsed ? ' is-ai-collapsed' : ''}${isAiOpen ? ' is-ai-open' : ''}${isMaterialPreviewOpen ? ' is-material-preview-open' : ''}${isAiResizing ? ' is-ai-resizing' : ''}`}
      style={appShellStyle}
    >
      <MainNavigation
        activeModule={activeModule}
        onModuleChange={changeActiveModule}
        userName={authUser?.displayName}
        onLogout={isDemoMode ? undefined : handleLogout}
      />

      <main className="main-area">
        <header className="topbar">
          <div className="mobile-brand">
            <span>期末粥加速器</span>
          </div>

          <div className="topbar-context">
            <div className="crumbs">
              <span className="section-dot" aria-hidden="true"></span>
              <span>{modelProfile.status === 'connected' ? 'AI 已连接' : '本地资料模式'}</span>
              <span className="crumb-divider">/</span>
              <span>{activeCourse.name}</span>
            </div>
            <div className="topbar-status">
              <Sparkles size={13} />
              <span>{activeWorkspace.materials.length ? `${activeWorkspace.materials.length} 份资料已索引` : `${activeWorkspace.course.name}课程已建立`}</span>
              <Clock3 size={13} />
              <span>每天 {activeWorkspace.course.dailyHours}h · 目标 {activeWorkspace.course.targetScore}+</span>
            </div>
          </div>

          <TopbarCourseTimer
            activeCourseId={activeWorkspace.course.id}
            activeCourseName={activeWorkspace.course.name}
          />

          <div className="topbar-actions">
            <CourseSwitcher
              courses={courses}
              activeCourse={activeCourse}
              isOpen={isCourseMenuOpen}
              menuRef={courseMenuRef}
              onToggle={() => setIsCourseMenuOpen((current) => !current)}
              onSelectCourse={(course) => { void handleSelectCourse(course) }}
              onDeleteCourse={handleDeleteCourse}
              onNewCourse={() => {
                setIsCourseMenuOpen(false)
                setIsNewCourseOpen(true)
              }}
            />
            <button className="search-button" type="button" onClick={() => setSearchOpen(true)}>
              <Search size={16} />
              <span>搜索资料 / 知识点</span>
              <kbd>Ctrl K</kbd>
            </button>
            <button
              className="icon-button"
              type="button"
              aria-label={theme === 'light' ? '切换深色模式' : '切换浅色模式'}
              onClick={() => setTheme((current) => (current === 'light' ? 'dark' : 'light'))}
            >
              {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
            </button>
            <QuickBackToTopButton />
            <button
              className="icon-button mobile-only"
              type="button"
              aria-label="打开 AI 伴学"
              onClick={() => setIsAiOpen(true)}
            >
              <PanelRightOpen size={19} />
            </button>
          </div>
        </header>

        <ModuleView
          activeModule={activeModule}
          courses={courses}
          courseWorkspaces={planningWorkspaces}
          course={activeWorkspace.course}
          courseProgress={courseProgress}
          completedTasks={completedTasks}
          tasks={activeWorkspace.tasks}
          knowledgePoints={activeWorkspace.knowledgePoints}
          practiceQuestions={activeWorkspace.practiceQuestions}
          mockQuestions={activeWorkspace.mockQuestions}
          practiceAnswers={activeWorkspace.practiceAnswers}
          mockResult={activeWorkspace.mockResult}
          materials={activeWorkspace.materials}
          materialMemory={activeWorkspace.materialMemory}
          assessmentProfile={activeWorkspace.assessmentProfile}
          diagnostic={activeWorkspace.diagnostic}
          wrongAnswers={activeWorkspace.wrongAnswers}
          archiveItems={archiveItems}
          note={activeWorkspace.note}
          onboarding={activeWorkspace.onboarding}
          strategyDocuments={activeWorkspace.strategyDocuments}
          strategyGenerationJob={strategyGenerationJob}
          diagnosticQuestions={activeWorkspace.diagnosticQuestions}
          modelProfile={modelProfile}
          theme={theme}
          uiFont={uiFont}
          uiFontSize={uiFontSize}
          onTasksChange={updateWorkspaceTasks}
          onWrongAnswersChange={updateWrongAnswers}
          onDeleteWrongAnswer={handleDeleteWrongAnswer}
          onRestoreArchiveItem={handleRestoreArchiveItem}
          onNoteChange={updateNote}
          onModelProfileChange={setModelProfile}
          onThemeChange={setTheme}
          onUiFontChange={setUiFont}
          onUiFontSizeChange={setUiFontSize}
          diagnosticReviewAnswers={diagnosticReviewAnswers}
          onModuleChange={changeActiveModule}
          onRescanMaterials={handleRescanMaterials}
          onUploadMaterials={handleUploadMaterials}
          onDeleteMaterial={handleDeleteMaterial}
          onSaveCourseSetup={handleSaveCourseSetup}
          onSubmitDiagnostic={handleSubmitDiagnostic}
          onGenerateStrategyDocuments={handleGenerateStrategyDocuments}
          onApproveStrategyDocuments={handleApproveStrategyDocuments}
          onRefreshWorkspace={handleRefreshWorkspace}
          onRepairStrategyGeneration={handleRepairStrategyGeneration}
          onSaveCoursePrompt={handleSaveCoursePrompt}
          onMaterialPreviewOpenChange={handleMaterialPreviewOpenChange}
          materialPreviewPath={materialPreviewPath}
          onMaterialPreviewRequestHandled={() => setMaterialPreviewPath(null)}
          onSubmitPractice={handlePracticeAnswer}
          onSubmitWrongAnswer={handleWrongAnswerRetry}
          onSubmitMock={handleMockSubmit}
          onClearPracticeAnswer={handleClearPracticeAnswer}
          onClearMockResult={handleClearMockResult}
          onActiveStudyTaskChange={setActiveStudyTaskId}
          planStartDate={activeWorkspace.planStartDate}
          timeLog={activeWorkspace.timeLog}
          dailyProgress={activeWorkspace.dailyProgress}
          pendingProposals={activeWorkspace.pendingProposals}
          onRecordTime={handleRecordTime}
          onDeleteTime={handleDeleteTime}
          onApplyProposal={handleApplyPlanProposal}
          onDismissProposal={handleDismissPlanProposal}
          onAdjustPlanParams={handleAdjustPlanParams}
        />
      </main>

      <AiCompanion
        className={isAiOpen ? 'is-open' : ''}
        course={activeWorkspace.course}
        messages={activeWorkspace.messages}
        proposal={proposal}
        modelProfile={modelProfile}
        isCollapsed={isAiCollapsed}
        onClose={() => setIsAiOpen(false)}
        onToggleCollapse={() => setIsAiCollapsed((current) => !current)}
        onResizeStart={handleAiPanelResizeStart}
        onApplyProposal={applyProposal}
        onDismissProposal={dismissProposal}
        onSendMessage={handleAgentMessage}
        streamingMessage={streamingMessage}
      />

      {isNewCourseOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={closeNewCourseModal}>
          <section
            className="new-course-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-course-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="modal-icon">
              <BookOpen size={21} />
            </div>
            <h2 id="new-course-title">新建课程</h2>
            <p>填写考试时间和目标，系统会先建立课程卡片与基础复习主线。</p>
            <form className="new-course-form" onSubmit={handleCreateCourse}>
              <label>
                课程名称
                <input
                  autoFocus
                  value={newCourseForm.name}
                  placeholder="例如：大学物理"
                  onChange={(event) => updateNewCourseForm('name', event.target.value)}
                />
              </label>
              <label>
                考试日期
                <input
                  type="date"
                  value={newCourseForm.examDate}
                  onChange={(event) => updateNewCourseForm('examDate', event.target.value)}
                />
              </label>
              <div className="new-course-grid">
                <label>
                  目标分数
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    value={newCourseForm.targetScore}
                    onChange={(event) => updateNewCourseForm('targetScore', event.target.value)}
                  />
                </label>
                <label>
                  每日可用
                  <input
                    type="number"
                    min="0.5"
                    max="24"
                    step="0.5"
                    value={newCourseForm.dailyHours}
                    onChange={(event) => updateNewCourseForm('dailyHours', event.target.value)}
                  />
                </label>
              </div>
              {newCourseError && <p className="form-error" role="alert">{newCourseError}</p>}
              <div className="modal-actions">
                <button className="secondary-button" type="button" disabled={isCreatingCourse} onClick={closeNewCourseModal}>
                  取消
                </button>
                <button className="primary-button" type="submit" disabled={isCreatingCourse}>
                  {isCreatingCourse ? '创建中' : '创建课程'}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {searchOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setSearchOpen(false)}>
          <section
            className="search-modal"
            role="dialog"
            aria-modal="true"
            aria-label="搜索"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <form className="search-form" onSubmit={handleSearch}>
              <Search size={19} aria-hidden="true" />
              <input
                autoFocus
                value={searchQuery}
                placeholder={`搜索${activeCourse.name}资料、知识点和笔记`}
                aria-label={`搜索${activeCourse.name}`}
                onChange={(event) => {
                  setSearchQuery(event.target.value)
                  setSearchResults([])
                  setSearchError('')
                  setHasSearched(false)
                }}
              />
              <button
                className="search-submit"
                type="submit"
                title="搜索"
                aria-label="搜索"
                disabled={!searchQuery.trim() || isSearching}
              >
                {isSearching ? <LoaderCircle className="is-spinning" size={17} /> : <Search size={17} />}
              </button>
              <button
                className="search-close"
                type="button"
                title="关闭"
                aria-label="关闭搜索"
                onClick={() => setSearchOpen(false)}
              >
                <X size={17} />
              </button>
            </form>

            <div className="search-results" aria-live="polite">
              {searchError && <p className="search-feedback is-error">{searchError}</p>}
              {!searchError && isSearching && <p className="search-feedback">正在检索当前课程...</p>}
              {!searchError && !isSearching && hasSearched && searchResults.length === 0 && (
                <p className="search-feedback">没有找到匹配内容</p>
              )}
              {!searchError && !isSearching && !hasSearched && (
                <p className="search-feedback">输入关键词后按 Enter 搜索</p>
              )}
              {!isSearching && searchResults.map((result) => (
                <button
                  className="search-result"
                  type="button"
                  key={result.id}
                  onClick={() => openSearchResult(result)}
                >
                  <span className="search-result-icon" aria-hidden="true">
                    {result.type === 'material' ? <FileText size={17} /> : <BookOpen size={17} />}
                  </span>
                  <span className="search-result-copy">
                    <strong>{result.title}</strong>
                    {result.excerpt && <span>{result.excerpt}</span>}
                    <small>{result.source || '当前课程'}</small>
                  </span>
                </button>
              ))}
            </div>
          </section>
        </div>
      )}

      <SelectionToNoteToolbar onAddToNote={appendNoteSnippet} />
    </div>
    </CourseTimerProvider>
    </GlossaryProvider>
  )
}

export default App
