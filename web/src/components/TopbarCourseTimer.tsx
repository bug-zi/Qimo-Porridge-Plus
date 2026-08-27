import { Pause, Play, Square, X } from 'lucide-react'
import { useCourseTimer } from '../hooks/useCourseTimer'

/**
 * 顶栏课程自动计时器：工作台打开即计时，可暂停、继续、立即记入或放弃本段。
 */
export function TopbarCourseTimer({
  activeCourseId,
  activeCourseName,
}: {
  activeCourseId: string
  activeCourseName: string
}) {
  const { timer, start, toggle, stopAndRecord, discard, recording } = useCourseTimer()

  if (!timer) {
    return (
      <div className="topbar-course-timer">
        <button
          className="tct-start"
          type="button"
          disabled={recording}
          onClick={() => start(activeCourseId, activeCourseName)}
        >
          <Play size={14} /> 开始计时
        </button>
      </div>
    )
  }

  const min = Math.floor(timer.elapsedSec / 60)
  const sec = timer.elapsedSec % 60
  const time = `${min}:${String(sec).padStart(2, '0')}`
  const showCourse = timer.courseId !== activeCourseId

  return (
    <div className={`topbar-course-timer ${timer.running ? 'is-running' : 'is-paused'}`}>
      <button
        className="tct-toggle"
        type="button"
        disabled={recording}
        aria-label={timer.running ? '暂停自动计时' : '继续自动计时'}
        title={timer.running ? '暂停' : '继续'}
        onClick={toggle}
      >
        {timer.running ? <Pause size={14} /> : <Play size={14} />}
      </button>
      <span className="tct-time" title={timer.running ? '正在自动记录学习时长' : '计时已暂停'}>{time}</span>
      {showCourse && <span className="tct-course">{timer.courseName}</span>}
      <button
        className="tct-icon-btn"
        type="button"
        disabled={recording}
        aria-label="立即记入本次整分钟时长"
        title="立即记入并开始新一段"
        onClick={() => {
          void stopAndRecord()
        }}
      >
        <Square size={13} />
      </button>
      <button
        className="tct-icon-btn"
        type="button"
        disabled={recording}
        aria-label="退出计时"
        title="退出计时"
        onClick={discard}
      >
        <X size={13} />
      </button>
    </div>
  )
}
