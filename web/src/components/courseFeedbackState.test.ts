import { describe, expect, it } from 'vitest'
import { feedbackDialogReducer, initialFeedbackDialogState } from './courseFeedbackState'

const proposal = {
  feedbackId: 'feedback-1',
  originalText: '旧内容',
  rewrittenText: '',
  rationale: '按用户要求删除',
  replaceable: true,
  target: { field: 'storySection.questions', itemIndex: '0' },
}

describe('feedbackDialogReducer', () => {
  it('shows proposal failures instead of the analysis success message', () => {
    const state = feedbackDialogReducer(initialFeedbackDialogState, {
      type: 'submitted',
      result: { feedbackId: 'feedback-1', status: 'analysis_failed', message: '反馈已记录', rewriteError: '修改建议生成失败' },
    })
    expect(state.phase).toBe('partial-success')
    expect(state.message).toBe('修改建议生成失败')
  })

  it('enters a deletion preview when rewritten text is empty', () => {
    const state = feedbackDialogReducer(initialFeedbackDialogState, {
      type: 'submitted',
      result: { feedbackId: 'feedback-1', status: 'awaiting_confirmation', message: '等待确认', rewriteProposal: proposal },
    })
    expect(state.phase).toBe('preview')
    expect(state.proposal?.rewrittenText).toBe('')
  })

  it('keeps the current proposal when refinement fails', () => {
    const preview = feedbackDialogReducer(initialFeedbackDialogState, { type: 'proposal', feedbackId: 'feedback-1', proposal })
    const failed = feedbackDialogReducer(preview, { type: 'failure', message: '网络失败', preserveProposal: true })
    expect(failed.phase).toBe('preview')
    expect(failed.proposal).toEqual(proposal)
  })

  it('lets the user apply only this occurrence', () => {
    const state = feedbackDialogReducer(initialFeedbackDialogState, { type: 'remember', value: false })
    expect(state.rememberPreference).toBe(false)
  })

  it('clears proposal data after explicit abandonment', () => {
    const preview = feedbackDialogReducer(initialFeedbackDialogState, { type: 'proposal', feedbackId: 'feedback-1', proposal })
    const abandoned = feedbackDialogReducer(preview, { type: 'abandoned' })
    expect(abandoned.phase).toBe('abandoned')
    expect(abandoned.proposal).toBeNull()
  })
})
