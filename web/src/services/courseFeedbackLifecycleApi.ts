import {
  abandonCourseFeedback,
  getOpenCourseFeedback,
  getCourseFeedbackRules,
  mergeCourseFeedbackRules,
  retryCourseFeedbackProposal,
  updateCourseFeedbackRule,
} from '../apiClient'
import type { CourseFeedbackOpenSession, CourseFeedbackOpenSessions, CourseFeedbackRuleAction } from '../types'

/**
 * Feedback lifecycle API compatibility boundary. The UI only consumes this module;
 * endpoint/path compatibility remains isolated while the backend contract settles.
 */
export const courseFeedbackLifecycleApi = {
  async listOpen(courseId: string): Promise<CourseFeedbackOpenSessions> {
    const response = await getOpenCourseFeedback(courseId)
    return { items: response.items.map((item): CourseFeedbackOpenSession => ({ ...item, context: item.context ?? {} })) }
  },
  retry: retryCourseFeedbackProposal,
  abandon: abandonCourseFeedback,
  listRules: getCourseFeedbackRules,
  mergeRules: mergeCourseFeedbackRules,
  updateRule: (courseId: string, ruleId: string, action: CourseFeedbackRuleAction) => updateCourseFeedbackRule(courseId, ruleId, action),
}
