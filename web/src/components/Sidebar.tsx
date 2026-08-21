import { useEffect, useMemo, useState } from 'react'
import { OptionWheel } from './OptionWheel'
import {
  Braces,
  CalendarDays,
  CircleCheck,
  ClipboardList,
  Database,
  ArchiveRestore,
  FileArchive,
  FileText,
  Grid2X2,
  LogOut,
  Network,
  Orbit,
  Plus,
  Sigma,
  SquarePen,
  Settings2,
  Target,
  Trash2,
  X,
} from 'lucide-react'
import type { Course, LearningModule } from '../types'
import {
  buildCourseTimeline,
  summarizeTimeline,
  COURSE_CATEGORY_TABS,
  type CourseTimelineCategory,
} from '../utils/courseTimeline'

type MainNavigationProps = {
  activeModule: LearningModule
  onModuleChange: (module: LearningModule) => void
  onLogout?: () => void
  userName?: string
}

type CoursePanelProps = {
  courses: Course[]
  activeCourseId: string
  onSelectCourse: (course: Course) => void
  onDeleteCourse: (course: Course) => void
  onNewCourse: () => void
  isOpen: boolean
  onClose: () => void
}

const moduleItems: { id: LearningModule; label: string; icon: typeof CircleCheck }[] = [
  { id: 'overview', label: '总览', icon: Grid2X2 },
  { id: 'materials', label: '资料库', icon: FileArchive },
  { id: 'planning', label: '规划', icon: CalendarDays },
  { id: 'mindmap', label: '知识地图', icon: Network },
  { id: 'plan', label: '复习主线', icon: CircleCheck },
  { id: 'practice', label: '刷题', icon: Target },
  { id: 'mock', label: '模拟卷', icon: ClipboardList },
  { id: 'notes', label: '笔记', icon: SquarePen },
  { id: 'errors', label: '错题本', icon: FileText },
  { id: 'archive', label: '归档', icon: ArchiveRestore },
]

function CourseGlyph({ course }: { course: Course }) {
  const iconProps = { size: 19, strokeWidth: 2.2 }
  switch (course.icon) {
    case 'code':
      return <Braces {...iconProps} />
    case 'physics':
      return <Orbit {...iconProps} />
    case 'math':
      return <Sigma {...iconProps} />
    case 'english':
      return <span className="course-letter">Aa</span>
    case 'system':
      return <Database {...iconProps} />
    default:
      return <Grid2X2 {...iconProps} />
  }
}

export function MainNavigation({ activeModule, onModuleChange, onLogout, userName }: MainNavigationProps) {
  return (
    <aside className="main-navigation">
      <button className="brand-button" type="button" aria-label="返回课程总览" onClick={() => onModuleChange('overview')}>
        <span className="brand-mark" aria-hidden="true"></span>
        <span className="brand-name">期末粥<br />加速器</span>
      </button>

      <div className="nav-section">
        {moduleItems.map((item) => {
          const Icon = item.icon
          return (
            <button
              className={`nav-item ${activeModule === item.id ? 'is-active' : ''}`}
              key={item.id}
              type="button"
              title={item.label}
              onClick={() => onModuleChange(item.id)}
            >
              <Icon size={20} />
              <span>{item.label}</span>
            </button>
          )
        })}
      </div>

      <div className="nav-bottom">
        {userName && <span className="nav-user" title={userName}>{userName}</span>}
        {onLogout && (
          <button
            className="nav-item"
            type="button"
            title="退出登录"
            onClick={onLogout}
          >
            <LogOut size={20} />
            <span>退出登录</span>
          </button>
        )}
        <button
          className={`nav-item ${activeModule === 'settings' ? 'is-active' : ''}`}
          type="button"
          title="设置"
          onClick={() => onModuleChange('settings')}
        >
          <Settings2 size={20} />
          <span>设置</span>
        </button>
      </div>
    </aside>
  )
}

export function CoursePanel({
  courses,
  activeCourseId,
  onSelectCourse,
  onDeleteCourse,
  onNewCourse,
  isOpen,
  onClose,
}: CoursePanelProps) {
  const [focusedCourseId, setFocusedCourseId] = useState(activeCourseId)
  // 当前查看的课程分类：默认「备考」，每次打开面板回到「备考」。
  const [activeTab, setActiveTab] = useState<CourseTimelineCategory>('active')

  // 外部（顶栏）切换 active 课程时，滚轮焦点跟随。
  useEffect(() => {
    setFocusedCourseId(activeCourseId)
  }, [activeCourseId])

  // 每次打开面板默认显示「备考」课程。
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

  // 切换分类或删除当前预览课程后，焦点落回 active 课程或该分类首门，避免滚轮指向不存在的项。
  useEffect(() => {
    if (ordered.length === 0) return
    if (ordered.some((c) => c.id === focusedCourseId)) return
    setFocusedCourseId(
      ordered.some((c) => c.id === activeCourseId) ? activeCourseId : ordered[0].id,
    )
  }, [ordered, focusedCourseId, activeCourseId])

  const safeIndex = Math.max(
    0,
    ordered.findIndex((c) => c.id === focusedCourseId),
  )
  const focused = ordered[safeIndex]

  return (
    <aside className={`course-panel ${isOpen ? 'is-open' : ''}`}>
      <header className="course-panel-header">
        <div>
          <span className="eyebrow">课程空间</span>
          <h2>我的课程 <small>({courses.length})</small></h2>
        </div>
        <button className="icon-button close-course-panel" type="button" aria-label="关闭课程列表" onClick={onClose}>
          <X size={18} />
        </button>
        <button className="add-course-button" type="button" aria-label="新建课程" onClick={onNewCourse}>
          <Plus size={19} />
        </button>
      </header>

      {timeline.length === 0 ? (
        <div className="course-empty">
          <span className="course-empty-text">还没有课程，新建一门开始吧</span>
          <button className="primary-button" type="button" onClick={onNewCourse}>
            <Plus size={16} /> 新建课程
          </button>
        </div>
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
            <div className="course-empty">
              <span className="course-empty-text">
                {activeTab === 'active' ? '还没有备考课程' : '还没有历史课程'}
              </span>
            </div>
          ) : (
            <>
              <div className="course-wheel-area">
                <OptionWheel
                  items={ordered.map((c) => c.name)}
                  index={safeIndex}
                  onChange={(i) => setFocusedCourseId(ordered[i].id)}
                  onActivate={() => focused && onSelectCourse(focused)}
                  ariaLabel="课程选择滚轮"
                />
              </div>

              {focused && (
                <article className="course-focus-card">
                  <div className="course-focus-head">
                    <span className="course-card-icon">
                      <CourseGlyph course={focused} />
                    </span>
                    <span className="course-card-content">
                      <span className="course-card-title-row">
                        <span className="course-card-title">{focused.name}</span>
                      </span>
                      <span className="course-card-meta">
                        {focused.examDate} <i></i> 目标 {focused.targetScore} 分
                      </span>
                      <span className="course-progress">
                        <span style={{ width: `${focused.progress}%` }}></span>
                      </span>
                      <span className="course-card-footer">
                        <span>每日可用 {focused.dailyHours} 小时</span>
                        <b>{focused.progress}%</b>
                      </span>
                    </span>
                  </div>
                  <div className="course-focus-actions">
                    <button
                      className="primary-button"
                      type="button"
                      onClick={() => onSelectCourse(focused)}
                    >
                      进入课程
                    </button>
                    <button
                      className="course-focus-delete"
                      type="button"
                      title={`删除 ${focused.name}`}
                      aria-label={`删除 ${focused.name}`}
                      onClick={() => onDeleteCourse(focused)}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </article>
              )}
            </>
          )}
        </>
      )}
    </aside>
  )
}
