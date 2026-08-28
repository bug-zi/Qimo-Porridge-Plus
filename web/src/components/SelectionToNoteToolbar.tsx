import { useEffect, useReducer, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, MessageSquareText, NotebookPen, RotateCcw, X } from 'lucide-react'
import { useTextSelection } from '../hooks/useTextSelection'
import { highlightSnippetSelection } from '../utils/noteHighlights'
import type { CourseFeedbackActionResult, CourseFeedbackContext, CourseFeedbackOpenSession, CourseFeedbackRefineResult, CourseFeedbackSelectionFragment, CourseFeedbackSubmitResult } from '../types'
import { CourseFeedbackPreview } from './CourseFeedbackPreview'
import { feedbackDialogReducer, initialFeedbackDialogState, isFeedbackBusy } from './courseFeedbackState'

export type CourseFeedbackDraft = {
  selectedText: string
  userComment: string
  context: CourseFeedbackContext
}

interface SelectionToNoteToolbarProps {
  onAddToNote: (text: string) => void
  onSubmitCourseFeedback?: (draft: CourseFeedbackDraft) => Promise<CourseFeedbackSubmitResult>
  onRefineCourseFeedback?: (feedbackId: string, extraComment: string, previousRewrite: string) => Promise<CourseFeedbackRefineResult>
  onApplyCourseFeedbackRewrite?: (feedbackId: string, rememberPreference: boolean) => Promise<string | void>
  onRetryCourseFeedback?: (feedbackId: string) => Promise<CourseFeedbackActionResult>
  onAbandonCourseFeedback?: (feedbackId: string) => Promise<CourseFeedbackActionResult>
  onLoadOpenCourseFeedback?: () => Promise<CourseFeedbackOpenSession | null>
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


export function SelectionToNoteToolbar({ onAddToNote, onSubmitCourseFeedback, onRefineCourseFeedback, onApplyCourseFeedbackRewrite, onRetryCourseFeedback, onAbandonCourseFeedback, onLoadOpenCourseFeedback }: SelectionToNoteToolbarProps) {
  const snapshot = useTextSelection()
  const [flash, setFlash] = useState(false)
  const [feedbackDraft, setFeedbackDraft] = useState<{ selectedText: string; context: CourseFeedbackContext } | null>(null)
  const [feedbackText, setFeedbackText] = useState('')
  const [state, dispatch] = useReducer(feedbackDialogReducer, initialFeedbackDialogState)
  const [refineText, setRefineText] = useState('')
  const [showRefineInput, setShowRefineInput] = useState(false)
  const flashTimer = useRef<number | undefined>(undefined)
  const successTimer = useRef<number | undefined>(undefined)

  useEffect(() => () => { window.clearTimeout(flashTimer.current); window.clearTimeout(successTimer.current) }, [])
  useEffect(() => {
    let cancelled = false
    setFeedbackDraft(null)
    dispatch({ type: 'reset' })
    if (!onLoadOpenCourseFeedback) return () => { cancelled = true }
    void onLoadOpenCourseFeedback().then((session) => {
      if (cancelled || !session?.rewriteProposal) return
      setFeedbackDraft({ selectedText: session.selectedText || session.rewriteProposal.originalText, context: session.context ?? session.rewriteProposal.target })
      dispatch({ type: 'proposal', feedbackId: session.feedbackId, proposal: session.rewriteProposal, message: '已恢复当前课程上次未确认的修改建议。' })
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [onLoadOpenCourseFeedback])

  const resetFeedback = () => { setFeedbackDraft(null); setFeedbackText(''); dispatch({ type: 'reset' }); setRefineText(''); setShowRefineInput(false) }
  const handleAdd = () => { if (!snapshot) return; highlightSnippetSelection(window.getSelection(), snapshot.text); onAddToNote(snapshot.text); setFlash(true); window.clearTimeout(flashTimer.current); flashTimer.current = window.setTimeout(() => { window.getSelection()?.removeAllRanges(); setFlash(false) }, FLASH_DURATION) }
  const openFeedback = () => { if (!snapshot) return; setFeedbackDraft({ selectedText: snapshot.text, context: feedbackContextFromSelection(snapshot.text) }); setFeedbackText(''); dispatch({ type: 'reset' }); setRefineText(''); setShowRefineInput(false) }
  const closeFeedback = () => { if (!isFeedbackBusy(state.phase)) resetFeedback() }

  const submitFeedback = async () => {
    if (!feedbackDraft || !onSubmitCourseFeedback) return
    const normalized = feedbackText.trim()
    if (!normalized) { dispatch({ type: 'failure', message: '请先写下你的课程意见。' }); return }
    dispatch({ type: 'working', phase: 'submitting' })
    try { dispatch({ type: 'submitted', result: await onSubmitCourseFeedback({ selectedText: feedbackDraft.selectedText, userComment: normalized, context: feedbackDraft.context }) }) }
    catch (error) { dispatch({ type: 'failure', message: error instanceof Error ? error.message : '课程意见提交失败，请稍后再试。' }) }
  }
  const retryProposal = async () => {
    if (!state.feedbackId || !onRetryCourseFeedback) return
    dispatch({ type: 'working', phase: 'submitting', message: '正在重试生成修改建议…' })
    try {
      const result = await onRetryCourseFeedback(state.feedbackId)
      if (result.rewriteProposal) dispatch({ type: 'proposal', feedbackId: state.feedbackId, proposal: { ...result.rewriteProposal, feedbackId: state.feedbackId }, message: result.message })
      else dispatch({ type: 'failure', message: result.rewriteError || result.message || '仍未生成修改建议。' })
    } catch (error) { dispatch({ type: 'failure', message: error instanceof Error ? error.message : '重试失败，请稍后再试。' }) }
  }
  const abandon = async () => {
    if (!state.feedbackId) { resetFeedback(); return }
    try { if (onAbandonCourseFeedback) await onAbandonCourseFeedback(state.feedbackId); dispatch({ type: 'abandoned' }); successTimer.current = window.setTimeout(resetFeedback, 700) }
    catch (error) { dispatch({ type: 'failure', message: error instanceof Error ? error.message : '放弃失败，请稍后重试。', preserveProposal: true }) }
  }
  const refineProposal = async () => {
    if (!state.proposal || !state.feedbackId || !onRefineCourseFeedback) return
    const normalized = refineText.trim(); if (!normalized) { dispatch({ type: 'failure', message: '请先写下希望继续修改的意见。', preserveProposal: true }); return }
    dispatch({ type: 'working', phase: 'refining', message: '正在重新生成…' })
    try { const result = await onRefineCourseFeedback(state.feedbackId, normalized, state.proposal.rewrittenText); dispatch({ type: 'proposal', feedbackId: result.feedbackId, proposal: { ...result.rewriteProposal, originalText: state.proposal.originalText, target: state.proposal.target }, message: '已根据补充意见更新建议。' }); setShowRefineInput(false); setRefineText('') }
    catch (error) { dispatch({ type: 'failure', message: error instanceof Error ? error.message : '继续修改失败，请稍后再试。', preserveProposal: true }) }
  }
  const applyRewrite = async () => {
    if (!state.proposal || !state.feedbackId || !onApplyCourseFeedbackRewrite) return
    dispatch({ type: 'working', phase: 'applying', message: '正在应用服务端最新修改建议…' })
    try { const message = await onApplyCourseFeedbackRewrite(state.feedbackId, state.rememberPreference); dispatch({ type: 'success', message: message || '已应用当前课程修改。' }); successTimer.current = window.setTimeout(() => { window.getSelection()?.removeAllRanges(); resetFeedback() }, 900) }
    catch (error) { dispatch({ type: 'failure', message: error instanceof Error ? error.message : '确认修改失败，请稍后再试。', preserveProposal: true }) }
  }

  let toolbar = null
  if (snapshot && !feedbackDraft && typeof document !== 'undefined') { const rect = snapshot.rect; const top = rect.top < TOOLBAR_HEIGHT + GAP + 8 ? rect.bottom + GAP : rect.top - TOOLBAR_HEIGHT - GAP; const left = Math.max(EDGE_PADDING, Math.min(rect.left + rect.width / 2, window.innerWidth - EDGE_PADDING)); toolbar = createPortal(<div className="selection-to-note-toolbar" role="toolbar" aria-label="选区操作" style={{ top, left }}><button type="button" className={flash ? 'is-done' : ''} onMouseDown={(event) => event.preventDefault()} onClick={handleAdd}>{flash ? <Check size={14} /> : <NotebookPen size={14} />}{flash ? '已加入笔记' : '添加到笔记'}</button>{onSubmitCourseFeedback && <button type="button" className="is-feedback" onMouseDown={(event) => event.preventDefault()} onClick={openFeedback}><MessageSquareText size={14} />课程意见反馈</button>}</div>, document.body) }
  const busy = isFeedbackBusy(state.phase)
  const dialog = feedbackDraft && typeof document !== 'undefined' ? createPortal(<div className="course-feedback-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeFeedback() }}><section className="course-feedback-dialog" role="dialog" aria-modal="true" aria-label="课程意见反馈"><header><div><span>课程意见反馈</span><h2>{state.proposal ? '课程内容优化建议' : state.phase === 'partial-success' ? '反馈已保存，建议生成失败' : '这段课程内容哪里需要优化？'}</h2></div><button type="button" className="course-feedback-close" onClick={closeFeedback} aria-label="关闭"><X size={18} /></button></header>
  {!state.proposal ? <><div className="course-feedback-selected"><strong>被反馈内容</strong><p>{feedbackDraft.selectedText}</p></div>{state.phase !== 'partial-success' && <label className="course-feedback-input"><span>反馈意见</span><textarea value={feedbackText} onChange={(event) => setFeedbackText(event.target.value)} rows={5} autoFocus disabled={busy || state.phase === 'success'} /></label>}</> : <><CourseFeedbackPreview proposal={state.proposal} context={feedbackDraft.context} rememberPreference={state.rememberPreference} onRememberPreferenceChange={(value) => dispatch({ type: 'remember', value })} />{showRefineInput && <label className="course-feedback-input"><span>补充意见</span><textarea value={refineText} onChange={(event) => setRefineText(event.target.value)} rows={3} autoFocus disabled={busy} /></label>}</>}
  {state.message && <p className={'course-feedback-message is-' + state.phase}>{state.message}</p>}
  <footer>{!state.proposal ? state.phase === 'partial-success' ? <><button type="button" className="ghost-button" onClick={abandon} disabled={busy}>放弃</button><button type="button" className="primary-button" onClick={retryProposal} disabled={busy || !onRetryCourseFeedback}><RotateCcw size={15} />重试生成修改建议</button></> : <><button type="button" className="ghost-button" onClick={closeFeedback} disabled={busy}>取消</button><button type="button" className="primary-button" onClick={submitFeedback} disabled={busy || state.phase === 'success'}>{state.phase === 'submitting' ? '生成中…' : '提交并生成优化'}</button></> : showRefineInput ? <><button type="button" className="ghost-button" onClick={() => setShowRefineInput(false)} disabled={busy}>返回对比</button><button type="button" className="primary-button" onClick={() => void refineProposal()} disabled={busy}>{state.phase === 'refining' ? '重新生成中…' : '重新生成'}</button></> : <><button type="button" className="ghost-button" onClick={closeFeedback} disabled={busy}>保留并关闭</button><button type="button" className="ghost-button" onClick={abandon} disabled={busy}>放弃</button><button type="button" className="ghost-button" onClick={() => setShowRefineInput(true)} disabled={busy}>继续修改</button><button type="button" className="primary-button" onClick={applyRewrite} disabled={busy}>{state.phase === 'applying' ? '应用中…' : state.proposal.rewrittenText ? '确认替换' : '确认删除'}</button></>}</footer></section></div>, document.body) : null
  return <>{toolbar}{dialog}</>
}
