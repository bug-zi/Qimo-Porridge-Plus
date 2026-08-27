/**
 * 「添加到笔记」摘录持久高光：CSS Custom Highlight API + localStorage 持久化。
 *
 * 为什么不用 <mark> 包裹选区：划选文本经常落在 React 托管的受控内容里
 * （Markdown 预览、AI 回答等），改写 DOM 会与虚拟 DOM 冲突，且跨节点
 * 选区很难安全包裹。Highlight API 只登记 Range、不动节点，天然共存；
 * 不支持的浏览器静默降级为无高光，添加笔记功能本身不受影响。
 *
 * 持久化：Range 无法序列化，且刷新后 DOM 重建、旧 Range 全部失效。因此
 * 保存的是「文本锚点」（Web Annotation TextQuoteSelector 的思路）——摘录
 * 在 .app-shell 拍平文本流中的起止偏移，外加前后各 32 字符的上下文锚。
 * 恢复时先按偏移定位并校验原文是否一致；不一致（内容前文被编辑过）回退
 * 用「前锚 + 摘录 + 后锚」全文搜索重新定位。AI 历史、课程资料等异步渲染
 * 的内容刷新后要等数据到位才出现在 DOM 里，定位不到的条目挂为 pending，
 * 由 MutationObserver 监听 .app-shell 变化后自动重试。
 *
 * 点击取消：Highlight API 没有命中事件，交互靠「视口坐标 → 文本位置 →
 * Range 判定」反查（见 findNoteHighlightAt）。
 */

/** CSS.highlights 注册表键，对应样式表里的 ::highlight(note-snippet) */
export const NOTE_HIGHLIGHT_NAME = 'note-snippet'

/** localStorage 键前缀，按课程隔离（与 final-congee-active-course 同风格） */
const STORAGE_PREFIX = 'final-congee-note-highlights:'

/** 前后文锚长度：太短容易撞车（常见词到处都是），太长浪费存储 */
const ANCHOR_LENGTH = 32

/** pending 重试防抖：流式渲染时 DOM 高频变化，文本索引重建开销不小 */
const RETRY_DEBOUNCE_MS = 200

/**
 * pending 重试上限：摘录所在模块被切走时锚点文本永远等不到（属预期，
 * 切回原模块会由 restore 重新定位），超过上限放弃并断开 observer，
 * 避免常驻监听 + 周期性全量重建文本索引。约 5 秒无恢复即放弃。
 */
const MAX_RETRIES = 25

/** 点击命中的高光条目；id 用于精确移除（同一段文本可能被多次摘录） */
export interface NoteHighlightHit {
  id: number
  snippet: string
}

/** 可序列化的文本锚点，刷新后据此在新 DOM 里重建 Range */
interface NoteHighlightRecord {
  id: number
  /** 归一化摘录文本，与笔记引用块内容一致，删除笔记时反查用 */
  snippet: string
  /** 摘录原文（textContent 原样，未做空白归一），定位与校验都用它 */
  domText: string
  start: number
  end: number
  prefix: string
  suffix: string
  /** 从笔记引用块反推生成：localStorage 丢失/换浏览器源时仍可恢复 */
  derivedFromNote?: boolean
}

interface NoteHighlightEntry {
  id: number
  snippet: string
  /** null 表示保存时无法计算锚点（如 root 缺失），该条仅本会话内存态 */
  record: NoteHighlightRecord | null
  /** 恢复成功的 Range；pending（尚未定位到 DOM）时为空 */
  ranges: Range[]
}

/** .app-shell 拍平文本流索引：全局偏移 ↔ 文本节点内偏移 互转用 */
interface TextIndex {
  nodes: Text[]
  starts: number[]
  text: string
  total: number
}

let nextEntryId = 1
let entries: NoteHighlightEntry[] = []
let currentCourseId: string | null = null
let retryTimer = 0
let retryCount = 0
let domObserver: MutationObserver | null = null

function getRegistry(): HighlightRegistry | undefined {
  if (typeof window === 'undefined') return undefined
  if (!('highlights' in CSS) || typeof Highlight === 'undefined') return undefined
  return CSS.highlights
}

function getAppShell(): Element | null {
  if (typeof document === 'undefined') return null
  // 启动/登录占位也带 .app-shell，但其中没有课程正文；如果在占位上恢复，
  // MutationObserver 会挂到稍后被卸载的节点，刷新后真实页面就不会再补挂高光。
  return document.querySelector('.app-shell:not(.boot-shell)')
}

/** 把登记表与 CSS.highlights 同步；条目清空时移除注册，避免残留空高光。 */
function syncRegistry() {
  const registry = getRegistry()
  if (!registry) return
  const ranges = entries.flatMap((entry) => entry.ranges)
  if (ranges.length > 0) {
    registry.set(NOTE_HIGHLIGHT_NAME, new Highlight(...ranges))
  } else {
    registry.delete(NOTE_HIGHLIGHT_NAME)
  }
}

/** 增删条目后立即落盘；存储不可用（隐私模式/配额）时仅内存态，不打断功能。 */
function persist() {
  if (!currentCourseId || typeof window === 'undefined') return
  try {
    const records = entries
      .map((entry) => entry.record)
      .filter((record): record is NoteHighlightRecord => record !== null)
    const key = STORAGE_PREFIX + currentCourseId
    if (records.length > 0) {
      window.localStorage.setItem(key, JSON.stringify(records))
    } else {
      window.localStorage.removeItem(key)
    }
  } catch {
    // localStorage 抛错时静默降级为本会话内存态
  }
}

function loadRecords(courseId: string): NoteHighlightRecord[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + courseId)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (item): item is NoteHighlightRecord =>
        !!item
        && typeof item === 'object'
        && typeof (item as NoteHighlightRecord).snippet === 'string'
        && typeof (item as NoteHighlightRecord).domText === 'string'
        && typeof (item as NoteHighlightRecord).start === 'number'
        && typeof (item as NoteHighlightRecord).end === 'number',
    )
  } catch {
    return []
  }
}

const HIGHLIGHT_EXCLUDE_SELECTOR = [
  '.right-notes-panel',
  '.notes-page',
  '.selection-to-note-toolbar',
  '.course-feedback-backdrop',
  '.note-highlight-dismiss',
  'input',
  'textarea',
  'select',
  'button',
  '[contenteditable="true"]',
  '[contenteditable=""]',
].join(',')

function isHighlightableTextNode(node: Text): boolean {
  if (!node.data) return false
  const parent = node.parentElement
  if (!parent) return false
  return !parent.closest(HIGHLIGHT_EXCLUDE_SELECTOR)
}

/** 遍历 root 下所有可高光正文文本节点，建立「节点起始偏移表」+ 拍平全文。 */
function buildTextIndex(root: Element): TextIndex {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      return isHighlightableTextNode(node as Text) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT
    },
  })
  const nodes: Text[] = []
  const starts: number[] = []
  const parts: string[] = []
  let pos = 0
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node as Text
    nodes.push(text)
    starts.push(pos)
    parts.push(text.data)
    pos += text.data.length
  }
  return { nodes, starts, text: parts.join(''), total: pos }
}

/**
 * 端点的全局偏移 = root 开头到该端点之间的「可高光正文」文本长度。
 * 不能用 Range#toString() 直接算整页文本，否则恢复时会优先命中笔记面板
 * 里刚追加的引用块，而不是原文位置。
 */
function globalOffsetBefore(root: Element, container: Node, offset: number): number | null {
  if (container.nodeType !== Node.TEXT_NODE) return null
  const target = container as Text
  if (!root.contains(target) || !isHighlightableTextNode(target)) return null
  const index = buildTextIndex(root)
  const nodeIndex = index.nodes.indexOf(target)
  if (nodeIndex < 0) return null
  return index.starts[nodeIndex] + Math.max(0, Math.min(offset, target.data.length))
}

/** 全局偏移 → 文本节点内位置；二分查找起始偏移表。 */
function resolveOffset(index: TextIndex, global: number): { node: Text; offset: number } | null {
  if (index.nodes.length === 0) return null
  if (global <= 0) return { node: index.nodes[0], offset: 0 }
  if (global >= index.total) {
    const last = index.nodes[index.nodes.length - 1]
    return { node: last, offset: last.data.length }
  }
  let lo = 0
  let hi = index.starts.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (index.starts[mid] <= global) lo = mid
    else hi = mid - 1
  }
  return { node: index.nodes[lo], offset: global - index.starts[lo] }
}

/**
 * 按文本锚点在当前 DOM 里重建 Range；定位不到返回 null（调用方挂 pending）。
 *
 * 三级定位：偏移直中（内容未变，最快）→ 前后锚组合搜索（前文被编辑过）
 * → 裸摘录搜索（前后文都变了但摘录还在，接受可能的撞车）。
 */
function recordFromSnippet(index: TextIndex, snippet: string, id: number): NoteHighlightRecord | null {
  const domText = snippet.trim()
  if (!domText) return null
  const start = index.text.indexOf(domText)
  if (start < 0) return null
  const end = start + domText.length
  return {
    id,
    snippet: domText,
    domText,
    start,
    end,
    prefix: index.text.slice(Math.max(0, start - ANCHOR_LENGTH), start),
    suffix: index.text.slice(end, end + ANCHOR_LENGTH),
    derivedFromNote: true,
  }
}

function extractQuotedSnippetsFromNote(note: string | undefined): string[] {
  if (!note) return []
  const lines = note.replace(/\r\n?/g, '\n').split('\n')
  const snippets: string[] = []
  for (let i = 0; i < lines.length; i += 1) {
    if (!lines[i].startsWith('>')) continue
    const block: string[] = []
    while (i < lines.length && lines[i].startsWith('>')) {
      block.push(lines[i].replace(/^> ?/, ''))
      i += 1
    }
    const text = block.join('\n').trim()
    if (text) snippets.push(text)
  }
  return snippets
}

function restoreRangeFromRecord(index: TextIndex, record: NoteHighlightRecord): Range | null {
  let start = -1
  if (record.end <= index.total && index.text.slice(record.start, record.end) === record.domText) {
    start = record.start
  } else {
    const anchored = index.text.indexOf(record.prefix + record.domText + record.suffix)
    if (anchored >= 0) {
      start = anchored + record.prefix.length
    } else {
      start = index.text.indexOf(record.domText)
    }
  }
  if (start < 0) return null

  const from = resolveOffset(index, start)
  const to = resolveOffset(index, start + record.domText.length)
  if (!from || !to) return null
  const range = document.createRange()
  try {
    range.setStart(from.node, from.offset)
    range.setEnd(to.node, to.offset)
  } catch {
    return null
  }
  return range
}

/** 有 pending 条目时保持观察：用户导航到锚点所在页面时唤醒重试。
 *  全部恢复后断开，避免常驻开销。 */
function ensureObserver() {
  if (domObserver || typeof MutationObserver === 'undefined') return
  const root = getAppShell()
  if (!root) return
  domObserver = new MutationObserver(() => {
    // 定时链可能已在等待上限处停转；DOM 变化（用户导航）时重置计数，
    // 让「总览页恢复不了、详情页才有锚点文本」的条目在导航后被重新捞起。
    retryCount = 0
    scheduleRetry()
  })
  domObserver.observe(root, { childList: true, subtree: true, characterData: true })
}

function scheduleRetry() {
  if (retryTimer || typeof window === 'undefined') return
  if (retryCount >= MAX_RETRIES) return
  retryCount += 1
  retryTimer = window.setTimeout(() => {
    retryTimer = 0
    retryPending()
  }, RETRY_DEBOUNCE_MS)
}

/** 内容（AI 历史、资料等异步数据）渲染到位后重试 pending 条目。 */
function retryPending() {
  const pending = entries.filter((entry) => entry.ranges.length === 0)
  if (pending.length === 0) {
    domObserver?.disconnect()
    domObserver = null
    return
  }
  const root = getAppShell()
  if (!root) return
  const index = buildTextIndex(root)
  let restored = false
  for (const entry of pending) {
    if (!entry.record) continue
    const range = restoreRangeFromRecord(index, entry.record)
    if (range) {
      entry.ranges.push(range)
      restored = true
    }
  }
  if (restored) syncRegistry()
  if (entries.every((entry) => entry.ranges.length > 0)) {
    domObserver?.disconnect()
    domObserver = null
    return
  }
  // 仍有 pending：自主排下一轮（内容静止、无 DOM 变化时也能推进到等待上限）；
  // 到达上限后定时链停转，等下一次 DOM 变化（导航）再重置计数唤醒。
  ensureObserver()
  scheduleRetry()
}

/** 只清内存态与观察器，不动 localStorage（restore 重新加载前调用）。 */
function resetInMemory() {
  entries = []
  retryCount = 0
  if (retryTimer && typeof window !== 'undefined') {
    window.clearTimeout(retryTimer)
    retryTimer = 0
  }
  domObserver?.disconnect()
  domObserver = null
}

/**
 * 把当前选区的 Range 克隆后登记为持久高光，同时计算文本锚点落盘。
 * 克隆的 Range 仍指向原节点但独立于选区，之后选区消失高光仍保留。
 */
export function highlightSnippetSelection(selection: Selection | null, snippet: string) {
  if (!selection || selection.rangeCount === 0 || !snippet.trim()) return
  if (typeof document === 'undefined') return

  const ranges: Range[] = []
  for (let i = 0; i < selection.rangeCount; i += 1) {
    ranges.push(selection.getRangeAt(i).cloneRange())
  }

  // 锚点取首个 Range 的起止（多 range 选区极少见，仅 Firefox Ctrl 加选会出现；
  // 此时高光仍全部登记，但持久化锚点只记首段，刷新后恢复首段）。
  const root = getAppShell()
  const first = ranges[0]
  let record: NoteHighlightRecord | null = null
  if (root) {
    const start = globalOffsetBefore(root, first.startContainer, first.startOffset)
    const end = globalOffsetBefore(root, first.endContainer, first.endOffset)
    if (start !== null && end !== null && end > start) {
      const index = buildTextIndex(root)
      record = {
        id: nextEntryId,
        snippet: snippet.trim(),
        domText: index.text.slice(start, end),
        start,
        end,
        prefix: index.text.slice(Math.max(0, start - ANCHOR_LENGTH), start),
        suffix: index.text.slice(end, end + ANCHOR_LENGTH),
      }
    }
  }

  entries.push({ id: nextEntryId, snippet: snippet.trim(), record, ranges })
  nextEntryId += 1
  syncRegistry()
  persist()
}

/**
 * 恢复指定课程的全部持久高光。切换课程/模块时调用：内容整体换掉，
 * 旧 Range 全部失效，这里按锚点在新 DOM 里逐条重建；定位不到的挂
 * pending，等异步内容渲染后由 MutationObserver 重试。
 *
 * 刷新后首帧 .app-shell 可能还没挂载（加载/登录占位界面），此时登记
 * courseId 后直接返回——App 渲染出 shell 后会带着同一 courseId 再次
 * 调用本函数完成恢复。
 */
export function restoreNoteHighlights(courseId: string, note?: string) {
  resetInMemory()
  currentCourseId = courseId || null
  if (!currentCourseId || typeof document === 'undefined') return

  const root = getAppShell()
  if (!root) return

  const index = buildTextIndex(root)
  const records = loadRecords(currentCourseId)
  const knownSnippets = new Set(records.map((record) => record.snippet))
  let nextId = records.reduce((max, record) => Math.max(max, record.id), 0) + 1

  // 兜底：高光锚点以笔记里的摘录引用块为长期来源。localStorage 在换端口、
  // 清缓存、某些 WebView 重启后可能不可用，但课程笔记会落到后端/快照；
  // 只要引用块仍在，就能从笔记反推出需要高光的文本并重新落盘。
  for (const snippet of extractQuotedSnippetsFromNote(note)) {
    if (knownSnippets.has(snippet)) continue
    const record = recordFromSnippet(index, snippet, nextId)
    if (!record) continue
    records.push(record)
    knownSnippets.add(snippet)
    nextId += 1
  }

  if (records.length === 0) return

  for (const record of records) {
    const range = restoreRangeFromRecord(index, record)
    entries.push({ id: record.id, snippet: record.snippet, record, ranges: range ? [range] : [] })
  }
  nextEntryId = records.reduce((max, record) => Math.max(max, record.id), 0) + 1
  syncRegistry()
  persist()
  if (entries.some((entry) => entry.ranges.length === 0)) {
    ensureObserver()
    scheduleRetry()
  }
}

/** 把视口坐标折算成文本位置；优先标准 caretPositionFromPoint，回退 WebKit 旧 API。 */
function textPositionFromPoint(x: number, y: number): { node: Node; offset: number } | null {
  if (typeof document.caretPositionFromPoint === 'function') {
    const position = document.caretPositionFromPoint(x, y)
    return position ? { node: position.offsetNode, offset: position.offset } : null
  }
  if (typeof document.caretRangeFromPoint === 'function') {
    const range = document.caretRangeFromPoint(x, y)
    return range ? { node: range.startContainer, offset: range.startOffset } : null
  }
  return null
}

/** 命中检测：视口坐标是否落在某条摘录高光上；未命中返回 null。 */
export function findNoteHighlightAt(x: number, y: number): NoteHighlightHit | null {
  if (entries.length === 0) return null
  const position = textPositionFromPoint(x, y)
  if (!position) return null
  for (const entry of entries) {
    for (const range of entry.ranges) {
      try {
        if (range.isPointInRange(position.node, position.offset)) {
          return { id: entry.id, snippet: entry.snippet }
        }
      } catch {
        // Range 指向的节点已随内容重渲染被卸载（跨文档根），该条视为失效跳过
      }
    }
  }
  return null
}

/** 移除一条摘录高光（点击取消时调用）并同步落盘，其余高光不受影响。 */
export function removeNoteHighlight(hit: NoteHighlightHit) {
  entries = entries.filter((entry) => entry.id !== hit.id)
  syncRegistry()
  persist()
}

/** 彻底清空当前课程的高光（内存 + 落盘）。 */
export function clearNoteHighlights() {
  resetInMemory()
  persist()
}

/** 删除课程时调用：清掉该课程的持久化高光，避免孤儿数据永久残留。 */
export function discardCourseNoteHighlights(courseId: string) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(STORAGE_PREFIX + courseId)
  } catch {
    // 存储不可用时无从清理，静默跳过
  }
}
