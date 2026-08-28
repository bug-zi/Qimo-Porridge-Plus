import { type CSSProperties, type FormEvent, memo, type PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Bot, Check, FilePenLine, LoaderCircle, MessageCircle, MessageCircleMore, NotebookPen, PanelRightClose, Send, Sparkles, X } from 'lucide-react'
import rehypeKatex from 'rehype-katex'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import 'katex/dist/katex.min.css'
import type { AdjustmentProposal, Course, GlobalCourseFeedbackResult, ModelProfile, PlanTask, StreamingMessage, StreamingToolEvent, StudyMessage } from '../types'
import { NotesSidebarPanel } from './NotesSidebarPanel'
import { glossaryMarkdownComponents } from '../glossary/termMatcher'

type RightPanel = 'ai' | 'notes'

type AiCompanionProps = {
  className?: string
  course: Course
  messages: StudyMessage[]
  proposal: AdjustmentProposal | null
  modelProfile: ModelProfile
  note: string
  activePanel: RightPanel
  isCollapsed: boolean
  onClose: () => void
  onToggleCollapse: () => void
  onSelectPanel: (panel: RightPanel) => void
  onResizeStart: (event: ReactPointerEvent<HTMLButtonElement>) => void
  onApplyProposal: () => void
  onDismissProposal: () => void
  onSendMessage: (message: string, mode: CompanionMode) => Promise<void>
  activeStudyTask: PlanTask | null
  activeStudySection: { index: number; id: string; label: string; title: string } | null
  onSubmitGlobalCourseFeedback: (taskId: string, sectionId: string, sectionIndex: number, userComment: string) => Promise<GlobalCourseFeedbackResult>
  onRefineGlobalCourseFeedback: (feedbackId: string, extraComment: string) => Promise<GlobalCourseFeedbackResult>
  onApplyGlobalCourseFeedback: (feedbackId: string, rememberPreference?: boolean) => Promise<string | void>
  onNoteChange: (note: string) => void
  streamingMessage?: StreamingMessage | null
  strategyReviewActive?: boolean
}

type CompanionMode = 'chat' | 'agent'

// 插件数组提为模块级常量：数组身份稳定，避免每次渲染都触发 ReactMarkdown 全量重解析
const remarkPlugins = [remarkGfm, remarkMath]
const rehypePlugins = [rehypeKatex]

const agentPrompts = [
  '检查今天的复习计划',
  '根据近期错题，给我一份计划调整提案',
  '今天任务做不完，帮我顺延并减负',
  '帮我生成一轮考前冲刺练习',
]

function formatLocalTime() {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date())
}

const bareLatexCommandPattern = /\\(?:cap|cup|setminus|overline|underline|frac|dfrac|tfrac|sqrt|times|cdot|div|pm|mp|leq?|geq?|neq|approx|equiv|in|notin|subset(?:eq)?|supset(?:eq)?|emptyset|forall|exists|neg|land|lor|Rightarrow|Leftrightarrow|sum|prod|int|lim|alpha|beta|gamma|delta|theta|lambda|mu|pi|sigma|phi|omega)\b/
const cjkPattern = /[\u3400-\u9fff]/

function formatAssistantContent(content: string) {
  const normalized = content
    .replace(/\r\n?/g, '\n')
    .replace(/\\\[((?:.|\n)*?)\\\]/g, (_, formula: string) => `\n\n$$\n${formula.trim()}\n$$\n\n`)
    .replace(/\\\((.+?)\\\)/g, (_, formula: string) => `$${formula.trim()}$`)
    .replace(/\*\*contentRefreshRecommended=true\*\*/g, '**资料已更新**')
    .replace(/contentRefreshRecommended=true/g, '资料已更新')
    .replace(/\s+---\s+(?=#{2,6}\s+)/g, '\n\n---\n\n')
    .replace(/\s+(#{2,6}\s+)/g, '\n\n$1')
    .replace(/\n{3,}/g, '\n\n')

  let insideCodeFence = false
  let insideMathBlock = false
  return normalized
    .split('\n')
    .map((line) => {
      const trimmed = line.trim()
      if (trimmed.startsWith('```')) {
        insideCodeFence = !insideCodeFence
        return line
      }
      if (!insideCodeFence && trimmed === '$$') {
        insideMathBlock = !insideMathBlock
        return line
      }
      if (insideCodeFence || insideMathBlock || !trimmed || trimmed.includes('$')) return line

      const listItem = line.match(/^(\s*(?:[-*+]|\d+[.)])\s+)(.+)$/)
      const prefix = listItem?.[1] ?? line.slice(0, line.length - line.trimStart().length)
      const formula = (listItem?.[2] ?? trimmed).trim()
      if (bareLatexCommandPattern.test(formula) && !cjkPattern.test(formula)) {
        return `${prefix}$${formula}$`
      }
      return line
    })
    .join('\n')
    .trim()
}

function renderToolEvents(events: StreamingToolEvent[]) {
  if (!events || events.length === 0) return null
  return (
    <ul className="chat-tool-events">
      {events.map((event, index) => (
        <li
          key={`${event.step}-${event.name}-${index}`}
          className={event.status === 'done' ? 'is-done' : 'is-running'}
        >
          <span className="chat-tool-icon">
            {event.status === 'done' ? (
              <Check size={13} />
            ) : (
              <LoaderCircle size={13} className="chat-tool-spin" />
            )}
          </span>
          <span>{event.status === 'done' && event.summary ? event.summary : event.label}</span>
        </li>
      ))}
    </ul>
  )
}

type StreamingChatMessageProps = {
  content: string
  toolEvents: StreamingToolEvent[]
  createdAt: string
  isAgentMode: boolean
}

/** 流式回复条目：独立 memo，token 增量只重渲染这一条，历史消息不受牵连。 */
const StreamingChatMessage = memo(function StreamingChatMessage({
  content,
  toolEvents,
  createdAt,
  isAgentMode,
}: StreamingChatMessageProps) {
  const streamingPlaceholder = isAgentMode ? 'Agent 正在思考…' : '正在组织回答…'
  return (
    <article className="chat-message is-pending is-streaming">
      {renderToolEvents(toolEvents)}
      <div className="chat-markdown">
        {content ? (
          <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={glossaryMarkdownComponents()}>
            {formatAssistantContent(content)}
          </ReactMarkdown>
        ) : (
          <p className="chat-streaming-placeholder">{streamingPlaceholder}</p>
        )}
        <span className="chat-cursor" aria-hidden="true">▍</span>
      </div>
      <time>{createdAt}</time>
    </article>
  )
})

type ChatMessageItemProps = {
  message: StudyMessage
  registerTurnRef: (id: string, node: HTMLElement | null) => void
}

/** 历史消息条目：memo 隔离，输入框打字 / 流式增量不再触发全部历史消息的 Markdown 重解析。 */
const ChatMessageItem = memo(function ChatMessageItem({ message, registerTurnRef }: ChatMessageItemProps) {
  return (
    <article
      className={`chat-message ${message.role === 'user' ? 'is-user' : ''} ${message.id === 'local-thinking' ? 'is-pending' : ''}`}
      ref={
        message.role === 'user'
          ? (node) => registerTurnRef(message.id, node)
          : undefined
      }
    >
      {message.role === 'assistant' && renderToolEvents(message.toolEvents ?? [])}
      {message.role === 'assistant' ? (
        <div className="chat-markdown">
          <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={glossaryMarkdownComponents()}>
            {formatAssistantContent(message.content)}
          </ReactMarkdown>
        </div>
      ) : (
        <p>{message.content}</p>
      )}
      <time>{message.createdAt}</time>
    </article>
  )
})

export function AiCompanion({
  className = '',
  course,
  messages,
  proposal,
  modelProfile,
  note,
  activePanel,
  isCollapsed,
  onClose,
  onToggleCollapse,
  onSelectPanel,
  onResizeStart,
  onApplyProposal,
  onDismissProposal,
  onSendMessage,
  activeStudyTask,
  activeStudySection,
  onSubmitGlobalCourseFeedback,
  onRefineGlobalCourseFeedback,
  onApplyGlobalCourseFeedback,
  onNoteChange,
  streamingMessage,
  strategyReviewActive = false,
}: AiCompanionProps) {
  const [mode, setMode] = useState<CompanionMode>('chat')
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [pendingMessage, setPendingMessage] = useState<StudyMessage | null>(null)
  const [sendError, setSendError] = useState('')
  const [globalEditorOpen, setGlobalEditorOpen] = useState(false)
  const [globalComment, setGlobalComment] = useState('')
  const [globalResult, setGlobalResult] = useState<GlobalCourseFeedbackResult | null>(null)
  const [globalStatus, setGlobalStatus] = useState<'idle' | 'generating' | 'preview' | 'applying' | 'applied' | 'error'>('idle')
  const [globalMessage, setGlobalMessage] = useState('')
  const [globalRememberPreference, setGlobalRememberPreference] = useState(true)
  const [globalConversation, setGlobalConversation] = useState<Array<{ role: 'user' | 'assistant'; content: string }>>([])
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const stickRef = useRef(true) // 是否贴底跟随（用户上翻回看时为 false）
  const didInitRef = useRef(false) // 首次挂载时强制贴底一次
  const turnRefs = useRef<Map<string, HTMLElement>>(new Map())
  const [activeTurnIdx, setActiveTurnIdx] = useState(0)
  const [turnTooltip, setTurnTooltip] = useState<{ content: string; style: CSSProperties } | null>(null)
  const canSend = input.trim().length > 0 && !isSending
  const isAiPanel = activePanel === 'ai'
  const isStrategyReviewTakeover = isAiPanel && strategyReviewActive
  const panelClassName = ['ai-panel', isCollapsed ? 'is-collapsed' : '', isStrategyReviewTakeover ? 'is-strategy-review-takeover' : '', 'is-' + activePanel + '-panel', className].filter(Boolean).join(' ')
  const panelTitle = isAiPanel ? (isStrategyReviewTakeover ? '和 AI 商量' : 'AI 伴学') : '复习笔记'
  const panelSubtitle = isAiPanel
    ? isStrategyReviewTakeover
      ? '策略审阅 · 只修改当前草稿'
      : (modelProfile.status === 'connected' ? modelProfile.model : '未配置模型') + ' · ' + course.name
    : course.name + ' · 自动保存'
  const modeMessages = messages.filter((message) => (message.mode ?? 'chat') === mode)
  const thinkingText = mode === 'agent' ? 'Agent 已收到指令，正在拆解下一步行动...' : '我已收到，正在思考...'
  // 流式占位消息的时间戳取自本地上屏的用户消息
  const placeholderCreatedAt = pendingMessage?.createdAt ?? formatLocalTime()
  const placeholder: StudyMessage | null = pendingMessage
    ? streamingMessage
      ? {
          id: 'streaming',
          role: 'assistant',
          mode,
          content: streamingMessage.content || thinkingText,
          createdAt: pendingMessage.createdAt,
        }
      : {
          id: 'local-thinking',
          role: 'assistant',
          mode,
          content: thinkingText,
          createdAt: pendingMessage.createdAt,
        }
    : null
  const visibleMessages: StudyMessage[] = placeholder
    ? [...modeMessages, pendingMessage as StudyMessage, placeholder]
    : modeMessages

  const userTurns = visibleMessages.filter((message) => message.role === 'user')

  function updateActiveTurn() {
    const root = scrollRef.current
    if (!root) return
    const rootTop = root.getBoundingClientRect().top
    let next = 0
    userTurns.forEach((message, index) => {
      const node = turnRefs.current.get(message.id)
      if (node && node.getBoundingClientRect().top - rootTop <= 24) next = index
    })
    setActiveTurnIdx(next)
  }

  function handleScroll() {
    const el = scrollRef.current
    if (!el) return
    setTurnTooltip(null)
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    updateActiveTurn()
  }

  function jumpTo(messageId: string) {
    const node = turnRefs.current.get(messageId)
    if (!node) return
    node.scrollIntoView({ behavior: 'smooth', block: 'start' })
    stickRef.current = false // 跳转后不要被后续流式增量拉回底部
  }

  function showTurnTooltip(target: HTMLButtonElement, content: string) {
    const rect = target.getBoundingClientRect()
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight
    const width = Math.max(120, Math.min(260, viewportWidth - 24))
    const left = Math.max(12, Math.min(rect.left - width - 12, viewportWidth - width - 12))
    const top = Math.min(Math.max(12, rect.top - 14), Math.max(12, viewportHeight - 36))
    setTurnTooltip({
      content,
      style: {
        left,
        top,
        width,
        maxHeight: Math.max(72, viewportHeight - top - 12),
      },
    })
  }

  useEffect(() => {
    setGlobalResult(null)
    setGlobalConversation([])
    setGlobalComment('')
    setGlobalStatus('idle')
    setGlobalMessage('')
  }, [activeStudyTask?.id, activeStudySection?.id, activeStudySection?.index])

  // 智能粘底：首次挂载强制贴底；之后仅在用户本就贴底时跟随流式增量
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    if (!didInitRef.current) {
      el.scrollTop = el.scrollHeight
      didInitRef.current = true
      return
    }
    if (stickRef.current) el.scrollTop = el.scrollHeight
  }, [visibleMessages.length, streamingMessage?.content])

  // 切 Chat/Agent：重新贴底并重算当前轮
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    stickRef.current = true
    el.scrollTop = el.scrollHeight
    updateActiveTurn()
  }, [mode])

  // 消息增减后当前轮索引可能漂移，重算
  useEffect(() => {
    updateActiveTurn()
  }, [visibleMessages.length])

  async function sendMessage() {
    const trimmed = input.trim()
    if (!trimmed || isSending) return

    const optimisticMessage: StudyMessage = {
      id: `local-user-${Date.now()}`,
      role: 'user',
      mode,
      content: trimmed,
      createdAt: formatLocalTime(),
    }

    setInput('')
    setIsSending(true)
    setSendError('')
    setPendingMessage(optimisticMessage)
    try {
      await onSendMessage(trimmed, mode)
    } catch (error) {
      setSendError(error instanceof Error ? error.message : '消息发送失败，请稍后再试。')
      setInput((current) => current || trimmed)
    } finally {
      setPendingMessage(null)
      setIsSending(false)
    }
  }

  async function generateGlobalRevision() {
    const comment = globalComment.trim()
    if (!activeStudyTask?.studyGuide || !activeStudySection) {
      setGlobalStatus('error')
      setGlobalMessage('请先打开课程中的一个小节，再提交整体修改。')
      return
    }
    if (!comment) {
      setGlobalStatus('error')
      setGlobalMessage('请写下你希望对当前小节进行的修改。')
      return
    }
    setGlobalStatus('generating')
    setGlobalMessage('')
    try {
      const result = await onSubmitGlobalCourseFeedback(activeStudyTask.id, activeStudySection.id, activeStudySection.index, comment)
      setGlobalResult(result)
      setGlobalConversation([
        { role: 'user', content: comment },
        { role: 'assistant', content: result.proposal.changeSummary + (result.proposal.rationale ? `\n${result.proposal.rationale}` : '') },
      ])
      setGlobalComment('')
      setGlobalStatus('preview')
      setGlobalMessage(result.message)
    } catch (error) {
      setGlobalStatus('error')
      setGlobalMessage(error instanceof Error ? error.message : '小节修改生成失败，请稍后再试。')
    }
  }

  async function refineGlobalRevision() {
    const comment = globalComment.trim()
    if (!globalResult || !comment || globalStatus === 'generating') return
    setGlobalStatus('generating')
    setGlobalMessage('')
    try {
      const result = await onRefineGlobalCourseFeedback(globalResult.feedbackId, comment)
      setGlobalResult(result)
      setGlobalConversation((current) => [
        ...current,
        { role: 'user', content: comment },
        { role: 'assistant', content: result.proposal.changeSummary + (result.proposal.rationale ? `\n${result.proposal.rationale}` : '') },
      ])
      setGlobalComment('')
      setGlobalStatus('preview')
      setGlobalMessage(result.message)
    } catch (error) {
      setGlobalStatus('preview')
      setGlobalMessage(error instanceof Error ? error.message : '继续修改失败，请稍后再试。')
    }
  }

  async function applyGlobalRevision() {
    if (!globalResult) return
    setGlobalStatus('applying')
    try {
      const message = await onApplyGlobalCourseFeedback(globalResult.feedbackId, globalRememberPreference)
      setGlobalStatus('applied')
      setGlobalMessage(message || '已应用当前小节修改。')
    } catch (error) {
      setGlobalStatus('error')
      setGlobalMessage(error instanceof Error ? error.message : '全局修改应用失败，请重新生成。')
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void sendMessage()
  }

  function resizeInput() {
    const textarea = inputRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 240)}px`
    textarea.style.overflowY = textarea.scrollHeight > 240 ? 'auto' : 'hidden'
  }

  useEffect(() => {
    resizeInput()
  }, [input])

  useEffect(() => {
    const textarea = inputRef.current
    const container = textarea?.parentElement
    if (!container || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(resizeInput)
    observer.observe(container)
    return () => observer.disconnect()
  }, [])

  // 稳定回调：避免 memo 的 ChatMessageItem 因内联箭头函数身份变化而失效
  const registerTurnRef = useCallback((id: string, node: HTMLElement | null) => {
    if (node) turnRefs.current.set(id, node)
    else turnRefs.current.delete(id)
  }, [])

  function renderMessage(message: StudyMessage) {
    if (message.id === 'streaming' && streamingMessage) {
      return (
        <StreamingChatMessage
          key="streaming"
          content={streamingMessage.content}
          toolEvents={streamingMessage.toolEvents}
          createdAt={placeholderCreatedAt}
          isAgentMode={mode === 'agent'}
        />
      )
    }
    return <ChatMessageItem key={message.id} message={message} registerTurnRef={registerTurnRef} />
  }

  return (
    <aside className={panelClassName} aria-label="AI 伴学">
      <button
        className="ai-resize-handle"
        type="button"
        aria-label="拖拽调整 AI 伴学宽度"
        title="拖拽调整 AI 伴学宽度"
        onPointerDown={onResizeStart}
      />

      <div className="ai-collapsed-rail">
        <button
          className={["ai-collapsed-brand", activePanel === 'ai' ? 'is-active' : ''].filter(Boolean).join(' ')}
          type="button"
          aria-label="展开 AI 伴学"
          title="展开 AI 伴学"
          aria-expanded={!isCollapsed && activePanel === 'ai'}
          onClick={() => onSelectPanel('ai')}
        >
          <span className="ai-avatar"><MessageCircleMore size={18} /></span>
          <span>AI<br />伴学</span>
        </button>
        <button
          className={["ai-collapsed-brand", activePanel === 'notes' ? 'is-active' : ''].filter(Boolean).join(' ')}
          type="button"
          aria-label="展开复习笔记"
          title="展开复习笔记"
          aria-expanded={!isCollapsed && activePanel === 'notes'}
          onClick={() => onSelectPanel('notes')}
        >
          <span className="ai-avatar"><NotebookPen size={18} /></span>
          <span>复习<br />笔记</span>
        </button>
      </div>

      <header className="ai-panel-header">
        <div className="ai-panel-identity">
          <span className="ai-avatar">
            {isAiPanel ? <MessageCircleMore size={18} /> : <NotebookPen size={18} />}
          </span>
          <div>
            <h2>{panelTitle}</h2>
            <span>{panelSubtitle}</span>
          </div>
        </div>
        <div className="ai-panel-actions">
          <button
            className="icon-button ai-collapse-toggle"
            type="button"
            aria-label={isAiPanel ? '收起 AI 伴学' : '收起复习笔记'}
            title={isAiPanel ? '收起 AI 伴学' : '收起复习笔记'}
            aria-expanded={!isCollapsed}
            onClick={onToggleCollapse}
          >
            <PanelRightClose size={17} />
          </button>
          <button className="icon-button ai-close" type="button" aria-label={isAiPanel ? '关闭 AI 伴学' : '关闭复习笔记'} onClick={onClose}>
            <X size={18} />
          </button>
        </div>
      </header>

      {isAiPanel ? (
        isStrategyReviewTakeover ? (
          <div id="strategy-revision-slot" className="strategy-revision-takeover-slot">
            <section className="strategy-revision-placeholder">
              <Sparkles size={18} />
              <strong>正在连接策略草稿…</strong>
              <p>打开策略审阅页后，可以直接在这里让 AI 修改两份草稿。</p>
            </section>
          </div>
        ) : (
        <>
          <div className="ai-mode-switch" role="tablist" aria-label="伴学模式">
            <button
              className={mode === 'chat' ? 'is-active' : ''}
              type="button"
              role="tab"
              aria-selected={mode === 'chat'}
              onClick={() => setMode('chat')}
            >
              <MessageCircle size={14} />
              <span>Chat</span>
            </button>
            <button
              className={mode === 'agent' ? 'is-active' : ''}
              type="button"
              role="tab"
              aria-selected={mode === 'agent'}
              onClick={() => setMode('agent')}
            >
              <Sparkles size={14} />
              <span>Agent</span>
            </button>
          </div>

          <div className="ai-scroll-wrap">
            <div className="ai-scroll" ref={scrollRef} onScroll={handleScroll}>
              <section className={`companion-card ${mode === 'agent' ? 'is-agent-mode' : ''}` }>
                <div className="companion-orb">
                  {mode === 'chat' ? <Bot size={37} /> : <Sparkles size={37} />}
                </div>
                {mode === 'chat' ? (
                  <>
                    <strong>晚好，冲刺的你很棒！</strong>
                    <p>我会根据你的资料、作答和时间安排，让每一段复习都更值钱。</p>
                  </>
                ) : (
                  <>
                    <strong>Agent 模式已待命</strong>
                    <p>我会把资料、计划和错题串起来，给你拆成下一步可以执行的动作。</p>
                  </>
                )}
              </section>


              {mode === 'chat' ? (
                <section className="chat-history" aria-label="AI 对话记录">
                  {visibleMessages.map(renderMessage)}
                </section>
              ) : (
                <section className="agent-workbench" aria-label="Agent 操作">
                  <div className="agent-workbench-heading">
                    <Sparkles size={18} />
                    <div>
                      <span>行动入口</span>
                      <strong>让 Agent 接管一段复习任务</strong>
                    </div>
                  </div>
                  <div className="agent-prompt-grid">
                    {agentPrompts.map((prompt) => (
                      <button type="button" key={prompt} onClick={() => setInput(prompt)}>
                        {prompt}
                      </button>
                    ))}
                  </div>
                  <div className="global-course-revision">
                    <button type="button" className="global-course-revision-trigger" onClick={() => setGlobalEditorOpen((current) => !current)}>
                      <FilePenLine size={16} />
                      <span><strong>整体修改当前小节</strong><small>无需划选，可追加、删除或重组这一小节</small></span>
                    </button>
                    {globalEditorOpen && (
                      <div className="global-course-revision-editor">
                        <p>修改范围：{activeStudyTask && activeStudySection ? `${activeStudyTask.title} · ${activeStudySection.label}` : '尚未打开具体小节'}</p>
                        {globalConversation.length > 0 && (
                          <div className="global-course-revision-conversation" aria-label="小节修改对话记录">
                            {globalConversation.map((turn, index) => (
                              <div key={index} className={'is-' + turn.role}>
                                <strong>{turn.role === 'user' ? '你' : 'AI'}</strong>
                                <p>{turn.content}</p>
                              </div>
                            ))}
                          </div>
                        )}
                        <textarea
                          value={globalComment}
                          onChange={(event) => setGlobalComment(event.target.value)}
                          placeholder={globalResult ? '继续告诉 AI 如何调整这一版，例如：总结再短一些，并保留刚才的例子。' : '例如：在本小节末尾增加一段总结；把这小节改成先例子后原理。'}
                          rows={4}
                          disabled={globalStatus === 'generating' || globalStatus === 'applying' || globalStatus === 'applied'}
                        />
                        <button
                          type="button"
                          className="primary-button"
                          onClick={() => void (globalResult ? refineGlobalRevision() : generateGlobalRevision())}
                          disabled={globalStatus === 'generating' || globalStatus === 'applying' || !globalComment.trim()}
                        >
                          {globalStatus === 'generating' ? 'AI 正在调整小节...' : globalResult ? '发送补充意见并更新预览' : '生成小节修改预览'}
                        </button>
                        {globalResult && globalStatus !== 'applied' && (
                          <div className="global-course-revision-preview">
                            <strong>当前小节修改预览</strong>
                            <p>{globalResult.proposal.changeSummary}</p>
                            {globalResult.proposal.rationale && <small>{globalResult.proposal.rationale}</small>}
                            <div className="proposal-actions">
                              <label className="course-feedback-remember">
                                <input type="checkbox" checked={globalRememberPreference} onChange={(event) => setGlobalRememberPreference(event.target.checked)} />
                                <span><strong>记住这个偏好</strong><small>取消勾选则只修改本次小节。</small></span>
                              </label>
                              <button type="button" className="primary-button" onClick={() => void applyGlobalRevision()} disabled={globalStatus === 'applying'}>
                                {globalStatus === 'applying' ? '应用中...' : '确认应用小节修改'}
                              </button>
                              <button type="button" className="secondary-button" onClick={() => { setGlobalResult(null); setGlobalConversation([]); setGlobalComment(''); setGlobalStatus('idle'); setGlobalMessage('') }}>开始新对话</button>
                            </div>
                          </div>
                        )}
                        {globalMessage && <p className={'global-course-revision-message is-' + globalStatus}>{globalMessage}</p>}
                      </div>
                    )}
                  </div>
                </section>
              )}

              {mode === 'agent' && visibleMessages.length > 0 && (
                <section className="chat-history" aria-label="Agent 交互记录">
                  {visibleMessages.map(renderMessage)}
                </section>
              )}

              {sendError && <p className="ai-send-error">{sendError}</p>}

              {mode === 'agent' && proposal && proposal.status === 'pending' && (
                <section className="proposal-card">
                  <div className="proposal-heading">
                    <Sparkles size={18} />
                    <div>
                      <span>调整提案</span>
                      <strong>{proposal.title}</strong>
                    </div>
                  </div>
                  <p>{proposal.reason}</p>
                  <div className="proposal-impact">{proposal.impact}</div>
                  <div className="proposal-actions">
                    <button className="primary-button" type="button" onClick={onApplyProposal}>
                      <Check size={16} /> 确认调整
                    </button>
                    <button className="secondary-button" type="button" onClick={onDismissProposal}>
                      暂不应用
                    </button>
                  </div>
                </section>
              )}

              {mode === 'agent' && proposal?.status === 'applied' && (
                <section className="applied-proposal">
                  <Check size={17} />
                  <span>已应用：{proposal.title}</span>
                </section>
              )}
            </div>
            {userTurns.length >= 1 && (
              <div className="chat-turn-rail" role="navigation" aria-label="跳转到某一轮对话">
                {userTurns.map((message, index) => (
                  <button
                    key={message.id}
                    type="button"
                    className={['chat-turn-dot', index === activeTurnIdx ? 'is-active' : ''].filter(Boolean).join(' ')}
                    aria-label={`跳转到第 ${index + 1} 轮提问`}
                    onFocus={(event) => showTurnTooltip(event.currentTarget, message.content)}
                    onBlur={() => setTurnTooltip(null)}
                    onPointerEnter={(event) => showTurnTooltip(event.currentTarget, message.content)}
                    onPointerLeave={() => setTurnTooltip(null)}
                    onClick={() => jumpTo(message.id)}
                  />
                ))}
              </div>
            )}
          </div>

          <form className="ai-input" onSubmit={handleSubmit}>
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              placeholder={mode === 'chat' ? '和我聊聊复习卡点...' : '让 Agent 检查计划、错题或资料...'}
              aria-label="输入给 AI 伴学的消息"
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault()
                  void sendMessage()
                }
              }}
            />
            <button type="submit" aria-label={mode === 'chat' ? '发送 Chat 消息' : '发送 Agent 指令'} disabled={!canSend}>
              <Send size={17} />
            </button>
          </form>
        </>
        )
      ) : (
        <NotesSidebarPanel note={note} onNoteChange={onNoteChange} />
      )}
      {turnTooltip && createPortal(
        <div className="chat-turn-tooltip" style={turnTooltip.style}>
          {turnTooltip.content}
        </div>,
        document.body,
      )}
    </aside>
  )
}