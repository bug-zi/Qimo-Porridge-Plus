import { useCallback, useEffect, useState } from 'react'
import { Combine, RefreshCw, Trash2 } from 'lucide-react'
import type { CourseFeedbackRule, CourseFeedbackRuleAction, CourseFeedbackRules } from '../types'
import { courseFeedbackLifecycleApi } from '../services/courseFeedbackLifecycleApi'

export function CoursePreferencesPanel({ courseId }: { courseId: string }) {
  const [data, setData] = useState<CourseFeedbackRules | null>(null)
  const [filter, setFilter] = useState<'active' | 'proposed' | 'inactive'>('active')
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const load = useCallback(async () => {
    setMessage('')
    try { setData(await courseFeedbackLifecycleApi.listRules(courseId)) }
    catch (error) { setMessage(error instanceof Error ? error.message : '课程偏好读取失败。') }
  }, [courseId])
  useEffect(() => { void load() }, [load])
  useEffect(() => { setSelected([]) }, [courseId, filter])

  async function update(rule: CourseFeedbackRule, action: CourseFeedbackRuleAction) {
    setBusy(rule.id); setMessage('')
    try { const result = await courseFeedbackLifecycleApi.updateRule(courseId, rule.id, action); setData(result.rules); setMessage(action === 'delete' ? '偏好已删除。' : '偏好状态已更新。') }
    catch (error) { setMessage(error instanceof Error ? error.message : '课程偏好更新失败。') }
    finally { setBusy('') }
  }

  async function mergeSelected() {
    if (selected.length < 2) return
    const [targetRuleId, ...sourceRuleIds] = selected
    setBusy('merge'); setMessage('')
    try {
      const result = await courseFeedbackLifecycleApi.mergeRules(courseId, targetRuleId, sourceRuleIds)
      setData(result.rules); setSelected([]); setMessage('所选偏好已合并；第一条规则作为保留项。')
    } catch (error) { setMessage(error instanceof Error ? error.message : '课程偏好合并失败。') }
    finally { setBusy('') }
  }

  const rules = data?.rules ?? []
  const visible = rules.filter((rule) => (rule.status || 'proposed') === filter)
  return <section className="course-preferences-panel">
    <header className="settings-panel-heading"><div><h2>当前课程偏好</h2><p>只有启用的偏好会进入后续课程生成；修改状态不会自动重写已有讲义。</p></div><button className="secondary-button" type="button" onClick={() => void load()}><RefreshCw size={15} />刷新</button></header>
    <div className="preference-tabs">{(['active', 'proposed', 'inactive'] as const).map((status) => <button key={status} type="button" className={filter === status ? 'is-active' : ''} onClick={() => setFilter(status)}>{status === 'active' ? '已启用' : status === 'proposed' ? '待确认' : '已停用'}（{rules.filter((rule) => (rule.status || 'proposed') === status).length}）</button>)}</div>
    {selected.length >= 2 && <div className="preference-merge-bar"><span>已选择 {selected.length} 条；列表中第一条作为保留规则。</span><button className="secondary-button" type="button" disabled={busy === 'merge'} onClick={() => void mergeSelected()}><Combine size={15} />合并所选</button></div>}
    {message && <p className="settings-message">{message}</p>}
    <div className="preference-list">{visible.length ? visible.map((rule) => <article key={rule.id}>
      <label className="preference-select"><input type="checkbox" checked={selected.includes(rule.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, rule.id] : current.filter((id) => id !== rule.id))} /><span className="sr-only">选择 {rule.title}</span></label>
      <div><strong>{rule.title || rule.type}</strong><p>{rule.description || rule.preferredPattern || '暂无说明'}</p><small>来源 {rule.sourceFeedbackIds?.length ?? 0} 条 · 权重 {rule.weight ?? 1}</small></div>
      <div>{rule.status !== 'active' && <button className="secondary-button" type="button" disabled={busy === rule.id} onClick={() => void update(rule, 'activate')}>启用</button>}{rule.status === 'active' && <button className="secondary-button" type="button" disabled={busy === rule.id} onClick={() => void update(rule, 'deactivate')}>停用</button>}<button className="secondary-button is-danger" type="button" disabled={busy === rule.id} onClick={() => void update(rule, 'delete')}><Trash2 size={15} />删除</button></div>
    </article>) : <p className="course-feedback-hint">当前状态下没有课程偏好。</p>}</div>
  </section>
}
