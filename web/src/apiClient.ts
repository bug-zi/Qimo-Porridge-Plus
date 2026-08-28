/**
 * API 门面：按 VITE_DEMO_MODE 分发到本地后端实现（./api）或演示模式实现（./demo/demoApi）。
 * 消费文件统一从这里 import，签名与类型与 ./api 完全一致。
 */
import * as localApi from './api'
import demoApi from './demo/demoApi'

const isDemo = import.meta.env.VITE_DEMO_MODE === 'true'
const impl = isDemo ? demoApi : localApi

export const listCourses = impl.listCourses
export const createCourse = impl.createCourse
export const deleteCourse = impl.deleteCourse
export const getCourseWorkspace = impl.getCourseWorkspace
export const reviewCourseReadability = impl.reviewCourseReadability
export const getCourseMindMap = impl.getCourseMindMap
export const generateCourseMindMap = impl.generateCourseMindMap
export const regroupCourseMindMapModules = impl.regroupCourseMindMapModules
export const saveCourseMindMap = impl.saveCourseMindMap
export const searchCourse = impl.searchCourse
export const saveCourseSetup = impl.saveCourseSetup
export const submitCourseDiagnostic = impl.submitCourseDiagnostic
export const getStrategyDocuments = impl.getStrategyDocuments
export const generateStrategyDocuments = impl.generateStrategyDocuments
export const saveStrategyDocuments = impl.saveStrategyDocuments
export const approveStrategyDocuments = impl.approveStrategyDocuments
export const approveStrategyDocumentsInBackground = impl.approveStrategyDocumentsInBackground
export const getAgentJob = impl.getAgentJob
export const cancelAgentJob = impl.cancelAgentJob
export const saveCoursePrompt = impl.saveCoursePrompt
export const submitCourseFeedback = impl.submitCourseFeedback
export const submitGlobalCourseFeedback = impl.submitGlobalCourseFeedback
export const refineGlobalCourseFeedback = impl.refineGlobalCourseFeedback
export const applyGlobalCourseFeedback = impl.applyGlobalCourseFeedback
export const getCourseFeedbackRules = impl.getCourseFeedbackRules
export const refineCourseFeedbackRewrite = impl.refineCourseFeedbackRewrite
export const applyCourseFeedbackRewrite = impl.applyCourseFeedbackRewrite
export const getCourseMaterialPreview = impl.getCourseMaterialPreview
export const getCourseMaterialFileUrl = impl.getCourseMaterialFileUrl
export const getCourseMaterialConvertedFileUrl = impl.getCourseMaterialConvertedFileUrl
export const rescanCourseMaterials = impl.rescanCourseMaterials
export const uploadCourseMaterials = impl.uploadCourseMaterials
export const updateCourseMaterialRole = impl.updateCourseMaterialRole
export const deleteCourseMaterial = impl.deleteCourseMaterial
export const getRuntimeModel = impl.getRuntimeModel
export const getModelUsage = impl.getModelUsage
export const saveRuntimeModel = impl.saveRuntimeModel
export const getModelProfiles = impl.getModelProfiles
export const saveModelProfile = impl.saveModelProfile
export const getBackupModel = impl.getBackupModel
export const saveBackupModel = impl.saveBackupModel
export const getAccountProfile = impl.getAccountProfile
export const saveAccountProfile = impl.saveAccountProfile
export const uploadAccountAvatar = impl.uploadAccountAvatar
export const deleteAccountAvatar = impl.deleteAccountAvatar
export const getUserProfilePrompt = impl.getUserProfilePrompt
export const saveUserProfilePrompt = impl.saveUserProfilePrompt
export const getEmbeddingProfile = impl.getEmbeddingProfile
export const saveEmbeddingProfile = impl.saveEmbeddingProfile
export const testEmbeddingProfile = impl.testEmbeddingProfile
export const rebuildKnowledgeEmbeddings = impl.rebuildKnowledgeEmbeddings
export const getKnowledgeBaseStatus = impl.getKnowledgeBaseStatus
export const submitCoursePracticeAnswer = impl.submitCoursePracticeAnswer
export const submitCourseWrongAnswerRetry = impl.submitCourseWrongAnswerRetry
export const repairCourseMockQuestions = impl.repairCourseMockQuestions
export const submitCourseMockAnswers = impl.submitCourseMockAnswers
export const clearCoursePracticeAnswer = impl.clearCoursePracticeAnswer
export const clearCourseMockResult = impl.clearCourseMockResult
export const updateCourseWorkspace = impl.updateCourseWorkspace
export const flushCourseWorkspaceNote = impl.flushCourseWorkspaceNote
export const recordCourseTimeLog = impl.recordCourseTimeLog
export const flushCourseTimeLog = impl.flushCourseTimeLog
export const deleteCourseTimeLog = impl.deleteCourseTimeLog
export const askCourseAgent = impl.askCourseAgent
export const streamCourseAgent = impl.streamCourseAgent
export const streamStrategyRevision = impl.streamStrategyRevision
export const applyCourseAdjustmentProposal = impl.applyCourseAdjustmentProposal
export const dismissCourseAdjustmentProposal = impl.dismissCourseAdjustmentProposal
export const adjustCoursePlan = impl.adjustCoursePlan
export const listMcpServers = impl.listMcpServers
export const saveMcpServer = impl.saveMcpServer
export const discoverMcpServer = impl.discoverMcpServer
export const getBilibiliCredentialStatus = impl.getBilibiliCredentialStatus
export const verifyBilibiliCredentials = impl.verifyBilibiliCredentials
export const saveBilibiliCredentials = impl.saveBilibiliCredentials
export const clearBilibiliCredentials = impl.clearBilibiliCredentials
export const submitCourseExternalSource = impl.submitCourseExternalSource
export const getCourseExternalSource = impl.getCourseExternalSource
export const approveCourseExternalSource = impl.approveCourseExternalSource
export const dismissCourseExternalSource = impl.dismissCourseExternalSource
export const deleteCourseWrongAnswer = impl.deleteCourseWrongAnswer
export const listArchiveItems = impl.listArchiveItems
export const restoreArchiveItem = impl.restoreArchiveItem
export const permanentlyDeleteArchiveItem = impl.permanentlyDeleteArchiveItem
export const toRuntimeModelProfile = impl.toRuntimeModelProfile
export const getCourseGlossary = impl.getCourseGlossary
export const getCourseGlossaryStatus = impl.getCourseGlossaryStatus
export const refreshCourseGlossary = impl.refreshCourseGlossary
export const updateGlossaryTerm = impl.updateGlossaryTerm
export const deleteGlossaryTerm = impl.deleteGlossaryTerm

export type {
  AgentStreamDone,
  AgentStreamHandlers,
  AgentStreamHandle,
  StrategyRevisionHandlers,
} from './api'

/** 演示模式标记：SettingsView 等需要短路真实网络请求的场合使用。 */
export const isDemoMode = isDemo
