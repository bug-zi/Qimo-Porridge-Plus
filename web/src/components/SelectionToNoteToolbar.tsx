import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, MessageSquareText, NotebookPen, X } from 'lucide-react'
import { useTextSelection } from '../hooks/useTextSelection'
import { highlightSnippetSelection } from '../utils/noteHighlights'
import type { CourseFeedbackContext, CourseFeedbackRefineResult, CourseFeedbackSelectionFragment, CourseFeedbackSubmitResult } from '../types'

export type CourseFeedbackDraft = {
  selectedText: string
  userComment: string
  context: CourseFeedbackContext
}

interface SelectionToNoteToolbarProps {
  onAddToNote: (text: string) => void
  onSubmitCourseFeedback?: (draft: CourseFeedbackDraft) => Promise<CourseFeedbackSubmitResult>
  onRefineCourseFeedback?: (feedbackId: string, extraComment: string, previousRewrite: string) => Promise<CourseFeedbackRefineResult>
  onApplyCourseFeedbackRewrite?: (feedbackId: string, originalText: string, rewrittenText: string, target: CourseFeedbackContext) => Promise<string | void>
}

const TOOLBAR_HEIGHT = 38
const GAP = 10
const EDGE_PADDING = 150
const FLASH_DURATION = 1100
const CONTEXT_RADIUS = 900

function closestElementFromSelection(selection: Selection | null): Element | null {
  if (!selection || selection.rangeCount === 0) return null
  const container = selection.getRangeAt(0).commonAncestorContainer
  return container.nodeType === Node.ELEMENT_NODE ? (container as Element) : container.parentElement
}

function elementFromNode(node: Node): Element | null {
  return node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement
}

function selectionFragmentsFromRange(range: Range): CourseFeedbackSelectionFragment[] {
  const root = elementFromNode(range.commonAncestorContainer)
  if (!root) return []
  const startScope = elementFromNode(range.startContainer)?.closest<HTMLElement>('[data-course-feedback-scope]') ?? null
  const candidates = root.matches('[data-course-feedback-field]')
    ? [root as HTMLElement, ...Array.from(root.querySelectorAll<HTMLElement>('[data-course-feedback-field]'))]
    : Array.from(root.querySelectorAll<HTMLElement>('[data-course-feedback-field]'))
  const fragments: CourseFeedbackSelectionFragment[] = []
  for (const node of candidates) {
    if (!range.intersectsNode(node)) continue
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT)
    let selectedText = ''
    for (let textNode = walker.nextNode(); textNode; textNode = walker.nextNode()) {
      const text = textNode.textContent ?? ''
      let start = 0
      let end = text.length
      if (textNode === range.startContainer) start = range.startOffset
      else if (range.comparePoint(textNode, text.length) < 0) continue
      if (textNode === range.endContainer) end = range.endOffset
      else if (range.comparePoint(textNode, 0) > 0) continue
      if (end > start) selectedText += text.slice(start, end)
    }
    selectedText = selectedText.trim()
    if (!selectedText) continue
    fragments.push({
      selectedText,
      field: node.dataset.courseFeedbackField ?? '',
      examPointId: node.dataset.examPointId ?? node.closest<HTMLElement>('[data-course-feedback-scope]')?.dataset.examPointId ?? startScope?.dataset.examPointId,
      exampleId: node.dataset.exampleId ?? node.closest<HTMLElement>('[data-course-feedback-scope]')?.dataset.exampleId ?? startScope?.dataset.exampleId,
      conceptTitle: node.dataset.conceptTitle ?? node.closest<HTMLElement>('[data-course-feedback-scope]')?.dataset.conceptTitle ?? startScope?.dataset.conceptTitle,
      itemIndex: node.dataset.itemIndex,
      sectionKind: node.dataset.sectionKind ?? node.closest<HTMLElement>('[data-story-section]')?.dataset.storySection,
    })
  }
  return fragments.filter((fragment) => fragment.field)
}

function feedbackContextFromSelection(selectedText: string): CourseFeedbackContext {
  const selection = window.getSelection()
  const element = closestElementFromSelection(selection)
  const range = selection?.rangeCount ? selection.getRangeAt(0) : null
  const startElement = range ? elementFromNode(range.startContainer) : element
  const endElement = range ? elementFromNode(range.endContainer) : element
  const fieldNode = startElement?.closest('[data-course-feedback-field]') as HTMLElement | null
  const startScope = startElement?.closest('[data-course-feedback-scope]') as HTMLElement | null
  const endScope = endElement?.closest('[data-course-feedback-scope]') as HTMLElement | null
  const scope = startScope ?? endScope
  const contextRoot = scope ?? fieldNode ?? element?.closest('article, section, main')
  const sectionText = ((contextRoot as HTMLElement | null)?.innerText || contextRoot?.textContent || '').trim()
  let beforeText = ''
  let afterText = ''
  let selectionFragments: CourseFeedbackSelectionFragment[] = []
  if (selection && selection.rangeCount > 0 && contextRoot) {
    const range = selection.getRangeAt(0)
    const sameTask = !startScope?.dataset.taskId || !endScope?.dataset.taskId || startScope.dataset.taskId === endScope.dataset.taskId
    selectionFragments = sameTask ? selectionFragmentsFromRange(range) : []
    try {
      const beforeRange = document.createRange()
      beforeRange.selectNodeContents(contextRoot)
      beforeRange.setEnd(range.startContainer, range.startOffset)
      beforeText = beforeRange.toString().trim().slice(-CONTEXT_RADIUS)
      beforeRange.detach()

      const afterRange = document.createRange()
      afterRange.selectNodeContents(contextRoot)
      afterRange.setStart(range.endContainer, range.endOffset)
      afterText = afterRange.toString().trim().slice(0, CONTEXT_RADIUS)
      afterRange.detach()
    } catch {
      beforeText = ''
      afterText = ''
    }
  }
  if (!beforeText && !afterText) {
    const selectedIndex = sectionText.indexOf(selectedText)
    beforeText = selectedIndex >= 0 ? sectionText.slice(Math.max(0, selectedIndex - CONTEXT_RADIUS), selectedIndex) : ''
    afterText = selectedIndex >= 0 ? sectionText.slice(selectedIndex + selectedText.length, selectedIndex + selectedText.length + CONTEXT_RADIUS) : ''
  }
  return {
    beforeText,
    afterText,
    sectionText: sectionText.slice(0, 6000),
    route: window.location.pathname + window.location.hash,
    taskId: scope?.dataset.taskId,
    taskTitle: scope?.dataset.taskTitle,
    moduleId: scope?.dataset.moduleId,
    knowledgePointId: scope?.dataset.knowledgePointId,
    sourceArea: scope?.dataset.courseFeedbackScope ?? 'unknown',
    field: fieldNode?.dataset.courseFeedbackField,
    examPointId: fieldNode?.dataset.examPointId ?? scope?.dataset.examPointId,
    exampleId: fieldNode?.dataset.exampleId ?? scope?.dataset.exampleId,
    conceptTitle: fieldNode?.dataset.conceptTitle ?? scope?.dataset.conceptTitle,
    itemIndex: fieldNode?.dataset.itemIndex,
    sectionKind: fieldNode?.dataset.sectionKind ?? fieldNode?.closest<HTMLElement>('[data-story-section]')?.dataset.storySection,
    selectionFragments: selectionFragments.length > 1 ? selectionFragments : undefined,
  }
}

export function SelectionToNoteToolbar({
  onAddToNote,
  onSubmitCourseFeedback,
  onRefineCourseFeedback,
  onApplyCourseFeedbackRewrite,
}: SelectionToNoteToolbarProps) {
  const snapshot = useTextSelection()
  const [flash, setFlash] = useState(false)
  const [feedbackDraft, setFeedbackDraft] = useState<{ selectedText: string; context: CourseFeedbackContext } | null>(null)
  const [feedbackText, setFeedbackText] = useState('')
  const [feedbackStatus, setFeedbackStatus] = useState<'idle' | 'submitting' | 'preview' | 'refining' | 'applying' | 'success' | 'error'>('idle')
  const [feedbackMessage, setFeedbackMessage] = useState('')
  const [feedbackId, setFeedbackId] = useState('')
  const [proposal, setProposal] = useState<CourseFeedbackSubmitResult['rewriteProposal'] | null>(null)
  const [refineText, setRefineText] = useState('')
  const [showRefineInput, setShowRefineInput] = useState(false)
  const flashTimer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(flashTimer.current), [])

  const resetFeedback = () => {
    setFeedbackDraft(null)
    setFeedbackText('')
    setFeedbackStatus('idle')
    setFeedbackMessage('')
    setFeedbackId('')
    setProposal(null)
    setRefineText('')
    setShowRefineInput(false)
  }

  const handleAdd = () => {
    if (!snapshot) return
    // 先登记高光锚点，再更新笔记面板。否则 React 追加引用块后，
    // 整页文本流会改变，持久化锚点可能指到笔记里的引用文本。
    highlightSnippetSelection(window.getSelection(), snapshot.text)
    onAddToNote(snapshot.text)
    setFlash(true)
    window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => {
      window.getSelection()?.removeAllRanges()
      setFlash(false)
    }, FLASH_DURATION)
  }

  const openFeedback = () => {
    if (!snapshot) return
    setFeedbackDraft({ selectedText: snapshot.text, context: feedbackContextFromSelection(snapshot.text) })
    setFeedbackText('')
    setFeedbackStatus('idle')
    setFeedbackMessage('')
    setFeedbackId('')
    setProposal(null)
    setRefineText('')
    setShowRefineInput(false)
  }

  const closeFeedback = () => {
    if (feedbackStatus === 'submitting' || feedbackStatus === 'refining' || feedbackStatus === 'applying') return
    resetFeedback()
  }

  const submitFeedback = async () => {
    if (!feedbackDraft || !onSubmitCourseFeedback) return
    const normalized = feedbackText.trim()
    if (!normalized) {
      setFeedbackStatus('error')
      setFeedbackMessage('请先写下你的课程意见。')
      return
    }
    setFeedbackStatus('submitting')
    setFeedbackMessage('')
    try {
      const result = await onSubmitCourseFeedback({ selectedText: feedbackDraft.selectedText, userComment: normalized, context: feedbackDraft.context })
      setFeedbackId(result.feedbackId)
      if (result.rewriteProposal) {
        setProposal(result.rewriteProposal)
        setFeedbackStatus('preview')
        setFeedbackMessage(result.message || '反馈意见1已记录，并生成了当前片段优化建议。')
      } else {
        setFeedbackStatus('success')
        setFeedbackMessage(result.message || result.rewriteError || '反馈意见已记录，但暂未生成改写建议。')
      }
    } catch (error) {
      setFeedbackStatus('error')
      setFeedbackMessage(error instanceof Error ? error.message : '课程意见提交失败，请稍后再试。')
    }
  }

  const refineProposal = async () => {
    if (!proposal) {
      setFeedbackMessage('当前没有可继续修改的优化版本，请先提交反馈生成一次优化。')
      return
    }
    const activeFeedbackId = feedbackId || proposal.feedbackId
    if (!activeFeedbackId) {
      setFeedbackMessage('缺少反馈记录 ID，无法继续修改；请重新提交反馈。')
      return
    }
    if (!onRefineCourseFeedback) {
      setFeedbackMessage('当前页面尚未接入继续修改接口，请刷新页面后重试。')
      return
    }
    const normalized = refineText.trim()
    if (!normalized) {
      setFeedbackMessage('请先写下希望继续修改的意见。')
      return
    }
    setFeedbackStatus('refining')
    setFeedbackMessage('正在根据反馈意见2重新生成，请稍候...')
    try {
      const result = await onRefineCourseFeedback(activeFeedbackId, normalized, proposal.rewrittenText)
      setProposal({ ...result.rewriteProposal, originalText: proposal.originalText, target: proposal.target })
      setFeedbackStatus('preview')
      setShowRefineInput(false)
      setRefineText('')
      setFeedbackMessage('已根据反馈意见2重新生成优化版本。')
    } catch (error) {
      setFeedbackStatus('preview')
      setFeedbackMessage(error instanceof Error ? error.message : '继续修改失败，请稍后再试。')
    }
  }

  const applyRewrite = async () => {
    if (!proposal) {
      setFeedbackMessage('当前没有可替换的优化版本，请先生成优化。')
      return
    }
    const activeFeedbackId = feedbackId || proposal.feedbackId
    if (!activeFeedbackId) {
      setFeedbackMessage('缺少反馈记录 ID，无法确认替换；请重新提交反馈。')
      return
    }
    if (!onApplyCourseFeedbackRewrite) {
      setFeedbackMessage('当前页面尚未接入确认替换接口，请刷新页面后重试。')
      return
    }
    setFeedbackStatus('applying')
    setFeedbackMessage('正在替换当前课程内容，请稍候...')
    try {
      const message = await onApplyCourseFeedbackRewrite(activeFeedbackId, proposal.originalText, proposal.rewrittenText, proposal.target)
      setFeedbackStatus('success')
      setFeedbackMessage(message || '已确认替换当前课程内容。')
      window.setTimeout(() => {
        window.getSelection()?.removeAllRanges()
        resetFeedback()
      }, 900)
    } catch (error) {
      setFeedbackStatus('preview')
      setFeedbackMessage(error instanceof Error ? error.message : '确认替换失败，请稍后再试。')
    }
  }

  let toolbar = null
  if (snapshot && !feedbackDraft && typeof document !== 'undefined') {
    const rect = snapshot.rect
    const placeBelow = rect.top < TOOLBAR_HEIGHT + GAP + 8
    const top = placeBelow ? rect.bottom + GAP : rect.top - TOOLBAR_HEIGHT - GAP
    const left = Math.max(EDGE_PADDING, Math.min(rect.left + rect.width / 2, window.innerWidth - EDGE_PADDING))
    toolbar = createPortal(
      <div className="selection-to-note-toolbar" role="toolbar" aria-label="选区操作" style={{ top, left }}>
        <button type="button" className={flash ? 'is-done' : ''} onMouseDown={(event) => event.preventDefault()} onClick={handleAdd}>
          {flash ? <Check size={14} /> : <NotebookPen size={14} />}
          {flash ? '已加入笔记' : '添加到笔记'}
        </button>
        {onSubmitCourseFeedback && (
          <button type="button" className="is-feedback" onMouseDown={(event) => event.preventDefault()} onClick={openFeedback}>
            <MessageSquareText size={14} />
            课程意见反馈
          </button>
        )}
      </div>,
      document.body,
    )
  }

  const busy = feedbackStatus === 'submitting' || feedbackStatus === 'refining' || feedbackStatus === 'applying'
  const dialog = feedbackDraft && typeof document !== 'undefined'
    ? createPortal(
        <div className="course-feedback-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeFeedback() }}>
          <section className="course-feedback-dialog" role="dialog" aria-modal="true" aria-label="课程意见反馈">
            <header>
              <div>
                <span>课程意见反馈</span>
                <h2>{proposal ? '课程内容优化建议' : '这段课程内容哪里需要优化？'}</h2>
              </div>
              <button type="button" className="course-feedback-close" onClick={closeFeedback} aria-label="关闭"><X size={18} /></button>
            </header>
            {!proposal ? (
              <>
                <div className="course-feedback-selected"><strong>被反馈内容</strong><p>{feedbackDraft.selectedText}</p></div>
                <label className="course-feedback-input">
                  <span>反馈意见1</span>
                  <textarea value={feedbackText} onChange={(event) => setFeedbackText(event.target.value)} placeholder="例如：这段太像百科定义了，希望先讲怎么用，再解释原理，并加一个具体例子。" rows={5} autoFocus disabled={busy || feedbackStatus === 'success'} />
                </label>
              </>
            ) : (
              <>
                <p className="course-feedback-hint">
                  反馈意见1已记录到优化库。当前替换目标：{String(proposal.target?.sourceArea ?? '课程内容')} / {String(proposal.target?.examPointId ?? proposal.target?.exampleId ?? proposal.target?.conceptTitle ?? proposal.target?.taskId ?? '当前选区')}。跨段选择会按划选时记录的结构锚点自动精确替换，你可以直接确认，或继续提出反馈意见2让 Agent 再改。
                </p>
                <div className="course-feedback-context-strip">
                  <p><strong>前文</strong>{feedbackDraft.context.beforeText || '（当前选区前没有更多同块内容）'}</p>
                </div>
                <div className="course-feedback-compare">
                  <section><strong>修改前</strong><p>{proposal.originalText}</p></section>
                  <section><strong>修改后</strong>{proposal.rewrittenText ? <p>{proposal.rewrittenText}</p> : <p className="course-feedback-delete-preview">这段内容将被删除</p>}</section>
                </div>
                <div className="course-feedback-context-strip is-after">
                  <p><strong>后文</strong>{feedbackDraft.context.afterText || '（当前选区后没有更多同块内容）'}</p>
                </div>
                {proposal.rationale && <p className="course-feedback-rationale">改写说明：{proposal.rationale}</p>}

                {showRefineInput && (
                  <label className="course-feedback-input">
                    <span>反馈意见2</span>
                    <textarea value={refineText} onChange={(event) => setRefineText(event.target.value)} placeholder="例如：这版还是太长，希望压缩成两条短句。" rows={3} autoFocus disabled={busy} />
                  </label>
                )}
              </>
            )}
            {feedbackMessage && <p className={'course-feedback-message is-' + feedbackStatus}>{feedbackMessage}</p>}
            <footer>
              {!proposal ? (
                <>
                  <button type="button" className="ghost-button" onClick={closeFeedback} disabled={busy}>取消</button>
                  <button type="button" className="primary-button" onClick={submitFeedback} disabled={busy || feedbackStatus === 'success'}>{feedbackStatus === 'submitting' ? '生成中...' : '提交并生成优化'}</button>
                </>
              ) : showRefineInput ? (
                <>
                  <button type="button" className="ghost-button" onClick={() => setShowRefineInput(false)} disabled={busy}>返回对比</button>
                  <button
                    type="button"
                    className="primary-button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      setFeedbackMessage('已点击重新生成，正在准备请求...')
                      void refineProposal()
                    }}
                    disabled={busy}
                  >
                    {feedbackStatus === 'refining' ? '重新生成中...' : '重新生成'}
                  </button>
                </>
              ) : (
                <>
                  <button type="button" className="ghost-button" onClick={closeFeedback} disabled={busy}>取消替换</button>
                  <button type="button" className="ghost-button" onClick={() => setShowRefineInput(true)} disabled={busy}>继续修改</button>
                  <button type="button" className="primary-button" onClick={applyRewrite} disabled={busy}>{feedbackStatus === 'applying' ? '应用中...' : proposal.rewrittenText ? '确认替换' : '确认删除'}</button>
                </>
              )}
            </footer>
          </section>
        </div>,
        document.body,
      )
    : null

  return <>{toolbar}{dialog}</>
}
