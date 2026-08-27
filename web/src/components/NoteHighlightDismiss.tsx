import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Trash2 } from 'lucide-react'
import { findNoteHighlightAt, type NoteHighlightHit } from '../utils/noteHighlights'

const TOOLBAR_HEIGHT = 38
const GAP = 10
const EDGE_PADDING = 90

/** 交互元素上的点击不参与命中检测，交给控件本身 */
const INTERACTIVE_SELECTOR =
  'button, a, input, textarea, select, [contenteditable="true"], [contenteditable=""], .glossary-term'

type ActiveHit = {
  hit: NoteHighlightHit
  x: number
  y: number
}

/**
 * 点击已高光的摘录 → 弹确认浮条 → 取消该条高光并从笔记移除对应引用块。
 *
 * 命中检测：CSS Custom Highlight API 没有事件，靠 findNoteHighlightAt 把
 * 点击坐标折算成文本位置后与登记的 Range 比对。不做成单击直接删除：
 * 用户经常在高光内重新划词或双击选词，误删笔记内容的代价高于多点一次确认。
 *
 * 与 SelectionToNoteToolbar 相同：portal 挂到 body，绕开 .app-shell 的 zoom。
 */
export function NoteHighlightDismiss({ onRemove }: { onRemove: (hit: NoteHighlightHit) => void }) {
  const [active, setActive] = useState<ActiveHit | null>(null)

  useEffect(() => {
    if (typeof document === 'undefined') return

    const hide = () => setActive(null)

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') hide()
    }

    const handleClick = (event: MouseEvent) => {
      const target = event.target as Element | null
      // 浮条自身（含确认按钮）的点击由组件内 onClick 处理
      if (target?.closest('.note-dismiss-popover')) return
      // 其他交互元素上的点击按原控件逻辑走，同时收起浮条
      if (target?.closest(INTERACTIVE_SELECTOR)) {
        hide()
        return
      }
      // 拖拽划词结束时也会派发 click；存在非折叠选区时视为划词而非点击
      const selection = window.getSelection()
      if (selection && !selection.isCollapsed && selection.toString().trim()) {
        hide()
        return
      }
      const hit = findNoteHighlightAt(event.clientX, event.clientY)
      setActive(hit ? { hit, x: event.clientX, y: event.clientY } : null)
    }

    const handleSelectionChange = () => {
      const selection = window.getSelection()
      if (selection && !selection.isCollapsed && selection.toString().trim()) hide()
    }

    document.addEventListener('click', handleClick)
    document.addEventListener('selectionchange', handleSelectionChange)
    document.addEventListener('keydown', handleKeyDown)
    // 点击坐标是瞬时锚点，滚动/缩放后不追踪，直接收起
    window.addEventListener('scroll', hide, true)
    window.addEventListener('resize', hide)

    return () => {
      document.removeEventListener('click', handleClick)
      document.removeEventListener('selectionchange', handleSelectionChange)
      document.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('scroll', hide, true)
      window.removeEventListener('resize', hide)
    }
  }, [])

  if (!active || typeof document === 'undefined') return null

  // 点击点贴近视口顶部时浮条改放到下方，避免被裁切
  const placeBelow = active.y < TOOLBAR_HEIGHT + GAP + 8
  const top = placeBelow ? active.y + GAP : active.y - TOOLBAR_HEIGHT - GAP
  const left = Math.max(EDGE_PADDING, Math.min(active.x, window.innerWidth - EDGE_PADDING))

  return createPortal(
    <div
      className="note-dismiss-popover"
      role="dialog"
      aria-label="高光摘录操作"
      style={{ top, left }}
    >
      <button
        type="button"
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => {
          onRemove(active.hit)
          setActive(null)
        }}
      >
        <Trash2 size={14} />
        移出笔记
      </button>
    </div>,
    document.body,
  )
}
