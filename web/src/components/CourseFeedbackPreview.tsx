import type { CourseFeedbackContext, CourseFeedbackRewriteProposal } from '../types'

type CourseFeedbackPreviewProps = {
  proposal: CourseFeedbackRewriteProposal
  context: CourseFeedbackContext
  rememberPreference: boolean
  onRememberPreferenceChange: (value: boolean) => void
}

export function CourseFeedbackPreview({ proposal, context, rememberPreference, onRememberPreferenceChange }: CourseFeedbackPreviewProps) {
  const listItem = proposal.target?.itemIndex !== undefined || proposal.target?.selectionFragments?.some((fragment) => fragment.itemIndex !== undefined)
  return <>
    <p className="course-feedback-hint">反馈已保存。当前修改目标：{String(proposal.target?.sourceArea ?? '课程内容')} / {String(proposal.target?.examPointId ?? proposal.target?.exampleId ?? proposal.target?.conceptTitle ?? proposal.target?.taskId ?? '当前选区')}。请核对后确认；未确认前不会修改课程。</p>
    <div className="course-feedback-context-strip"><p><strong>前文</strong>{context.beforeText || '（当前选区前没有更多同块内容）'}</p></div>
    <div className="course-feedback-compare">
      <section><strong>修改前</strong><p>{proposal.originalText}</p></section>
      <section><strong>修改后</strong>{proposal.rewrittenText ? <p>{proposal.rewrittenText}</p> : <p className="course-feedback-delete-preview">{listItem ? '这一个结构化列表项将被删除' : '这段内容将被删除'}</p>}</section>
    </div>
    <div className="course-feedback-context-strip is-after"><p><strong>后文</strong>{context.afterText || '（当前选区后没有更多同块内容）'}</p></div>
    {proposal.rationale && <p className="course-feedback-rationale">改写说明：{proposal.rationale}</p>}
    <label className="course-feedback-remember">
      <input type="checkbox" checked={rememberPreference} onChange={(event) => onRememberPreferenceChange(event.target.checked)} />
      <span><strong>记住这个偏好</strong><small>默认用于以后生成；取消勾选则只修改本次内容。</small></span>
    </label>
  </>
}
