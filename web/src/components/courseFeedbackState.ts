import type { CourseFeedbackRewriteProposal, CourseFeedbackSubmitResult } from '../types'

export type FeedbackPhase = 'idle' | 'submitting' | 'partial-success' | 'preview' | 'refining' | 'applying' | 'success' | 'error' | 'abandoned'

export type FeedbackDialogState = {
  phase: FeedbackPhase
  feedbackId: string
  proposal: CourseFeedbackRewriteProposal | null
  message: string
  rememberPreference: boolean
}

export const initialFeedbackDialogState: FeedbackDialogState = {
  phase: 'idle', feedbackId: '', proposal: null, message: '', rememberPreference: true,
}

export type FeedbackDialogAction =
  | { type: 'reset' }
  | { type: 'working'; phase: 'submitting' | 'refining' | 'applying'; message?: string }
  | { type: 'submitted'; result: CourseFeedbackSubmitResult }
  | { type: 'proposal'; feedbackId: string; proposal: CourseFeedbackRewriteProposal; message?: string }
  | { type: 'failure'; message: string; preserveProposal?: boolean }
  | { type: 'success'; message: string }
  | { type: 'abandoned'; message?: string }
  | { type: 'remember'; value: boolean }

export function feedbackDialogReducer(state: FeedbackDialogState, action: FeedbackDialogAction): FeedbackDialogState {
  switch (action.type) {
    case 'reset': return initialFeedbackDialogState
    case 'working': return { ...state, phase: action.phase, message: action.message ?? '' }
    case 'submitted': {
      const { result } = action
      if (result.rewriteProposal) return { ...state, phase: 'preview', feedbackId: result.feedbackId, proposal: result.rewriteProposal, message: result.message || '反馈已保存，并生成了修改建议。' }
      if (result.rewriteError) return { ...state, phase: 'partial-success', feedbackId: result.feedbackId, proposal: null, message: result.rewriteError }
      return { ...state, phase: 'success', feedbackId: result.feedbackId, proposal: null, message: result.message || '反馈已记录。' }
    }
    case 'proposal': return { ...state, phase: 'preview', feedbackId: action.feedbackId, proposal: action.proposal, message: action.message ?? '' }
    case 'failure': return { ...state, phase: action.preserveProposal && state.proposal ? 'preview' : 'error', message: action.message }
    case 'success': return { ...state, phase: 'success', message: action.message }
    case 'abandoned': return { ...state, phase: 'abandoned', proposal: null, message: action.message ?? '已放弃这次修改建议。' }
    case 'remember': return { ...state, rememberPreference: action.value }
  }
}

export function isFeedbackBusy(phase: FeedbackPhase) {
  return phase === 'submitting' || phase === 'refining' || phase === 'applying'
}
