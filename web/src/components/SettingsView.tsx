import { useEffect, useRef, useState } from 'react'
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  Database,
  Eye,
  EyeOff,
  KeyRound,
  Link2,
  LogOut,
  LoaderCircle,
  Moon,
  PlugZap,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
  Upload,
  Sun,
  UserRound,
} from 'lucide-react'
import {
  deleteAccountAvatar,
  discoverMcpServer,
  getBilibiliCredentialStatus,
  getEmbeddingProfile,
  getAccountProfile,
  getKnowledgeBaseStatus,
  getUserProfilePrompt,
  listMcpServers,
  rebuildKnowledgeEmbeddings,
  saveEmbeddingProfile,
  saveMcpServer,
  saveRuntimeModel,
  saveAccountProfile,
  saveUserProfilePrompt,
  testEmbeddingProfile,
  toRuntimeModelProfile,
  uploadAccountAvatar,
  isDemoMode,
} from '../apiClient'
import { BilibiliCredentialDialog } from './BilibiliCredentialDialog'
import { authFetch, type AuthUser } from '../auth'
import type {
  BilibiliCredentialStatus,
  EmbeddingProfile,
  KnowledgeBaseStatus,
  McpServer,
  ModelProfile,
  ModelProvider,
  UiFont,
  UiFontSize,
} from '../types'

type SettingsViewProps = {
  courseId: string
  modelProfile: ModelProfile
  theme: 'light' | 'dark'
  uiFont: UiFont
  uiFontSize: UiFontSize
  onModelProfileChange: (modelProfile: ModelProfile) => void
  onThemeChange: (theme: 'light' | 'dark') => void
  onUiFontChange: (font: UiFont) => void
  onUiFontSizeChange: (fontSize: UiFontSize) => void
  authUser: AuthUser | null
  onAuthUserChange: (user: AuthUser) => void
  onLogout?: () => void
}

type ProviderPreset = {
  id: ModelProvider
  label: string
  description: string
  baseUrl: string
  model: string
  supportsVision: boolean
}

type ConnectionResult = {
  success: boolean
  message: string
  available_models?: string[]
}


const providerPresets: ProviderPreset[] = [
  {
    id: 'openai',
    label: 'OpenAI',
    description: 'GPT 系列模型',
    baseUrl: 'https://api.openai.com/v1',
    model: 'gpt-4.1-mini',
    supportsVision: true,
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    description: 'DeepSeek 系列模型',
    baseUrl: 'https://api.deepseek.com',
    model: 'deepseek-chat',
    supportsVision: false,
  },
  {
    id: 'glm',
    label: 'GLM',
    description: '智谱 GLM 系列模型',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4-flash',
    supportsVision: true,
  },
  {
    id: 'custom',
    label: '自定义',
    description: 'OpenAI 兼容服务',
    baseUrl: '',
    model: 'gpt-5.5',
    supportsVision: true,
  },
]

const uiFontOptions: Array<{ id: UiFont; label: string; previewFamily: string }> = [
  {
    id: 'system',
    label: '系统默认',
    previewFamily: 'var(--font-system)',
  },
  {
    id: 'lakeus-night-writing',
    label: '851 远星夜行手写体',
    previewFamily: "'FinalCongee Lakeus Night Writing', var(--font-system)",
  },
  {
    id: 'maple-mono-nf-cn',
    label: 'MapleMono NF CN',
    previewFamily: "'FinalCongee Maple Mono NF CN', var(--font-system)",
  },
  {
    id: 'honglei-banshu',
    label: '鸿雷板书简体',
    previewFamily: "'FinalCongee Honglei Banshu', var(--font-system)",
  },
  {
    id: 'liyu-xingkai',
    label: '漓雨手书',
    previewFamily: "'FinalCongee Liyu Xingkai', var(--font-system)",
  },
  {
    id: 'nanxi-ink-song',
    label: '南西油墨宋',
    previewFamily: "'FinalCongee Nanxi Ink Song', var(--font-system)",
  },
  {
    id: 'lxgw-wenkai',
    label: '霞鹜文楷',
    previewFamily: "'FinalCongee LXGW WenKai', var(--font-system)",
  },
  {
    id: 'xuanzongti',
    label: '玄宗体',
    previewFamily: "'FinalCongee XuanZongTi', var(--font-system)",
  },
  {
    id: 'slidexiaxing',
    label: '演示夏行楷',
    previewFamily: "'FinalCongee Slidexiaxing', var(--font-system)",
  },
  {
    id: 'slideyouran',
    label: '演示悠然小楷',
    previewFamily: "'FinalCongee Slideyouran', var(--font-system)",
  },
]

const uiFontSizeOptions: UiFontSize[] = [90, 95, 100, 105, 110, 115]
const userProfilePromptMaxLength = 4000

const defaultEmbeddingProfile: EmbeddingProfile = {
  enabled: true,
  provider: 'ollama',
  baseUrl: 'http://127.0.0.1:11434',
  model: 'bge-m3',
  status: 'unavailable',
  message: '正在读取本地知识库状态。',
  indexedChunks: 0,
  totalChunks: 0,
  dimension: 0,
}

function getProviderPreset(provider: ModelProvider) {
  return providerPresets.find((item) => item.id === provider) ?? providerPresets[0]
}

function formatProviderName(provider: ModelProvider) {
  return getProviderPreset(provider).label
}

function statusContent(modelProfile: ModelProfile) {
  if (modelProfile.status === 'connected') {
    return { icon: CheckCircle2, tone: 'success', label: modelProfile.statusMessage || '连接成功' }
  }
  if (modelProfile.status === 'error') {
    return { icon: CircleAlert, tone: 'error', label: modelProfile.statusMessage || '连接失败' }
  }
  if (modelProfile.status === 'testing') {
    return { icon: LoaderCircle, tone: 'testing', label: modelProfile.statusMessage || '正在测试连接' }
  }
  if (modelProfile.status === 'saved') {
    return { icon: CheckCircle2, tone: 'saved', label: modelProfile.statusMessage || '配置已保存到本机' }
  }
  return { icon: CircleAlert, tone: 'neutral', label: '尚未配置 API Key' }
}

function resolveSelectedModel(currentModel: string, availableModels: string[]) {
  const trimmedModel = currentModel.trim()
  if (!availableModels.length) return currentModel
  if (trimmedModel && availableModels.includes(trimmedModel)) return trimmedModel
  return availableModels[0]
}

async function requestAvailableModels(profile: ModelProfile) {
  if (isDemoMode) {
    // 演示模式不发出真实网络请求，返回预设模型列表
    return {
      success: true,
      message: '演示模式：模型连接已模拟',
      available_models: ['gpt-5.4', 'deepseek-v4', 'glm-5.1'],
    } satisfies ConnectionResult
  }
  const response = await authFetch('/model-profiles/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      base_url: profile.baseUrl,
      api_key: profile.apiKey,
      model: profile.model,
    }),
  })
  const result = (await response.json()) as ConnectionResult
  if (!response.ok) {
    throw new Error(result.message || '模型服务请求失败')
  }
  return result
}

function toProfileWithAvailableModels(profile: ModelProfile, result: ConnectionResult): ModelProfile {
  const nextAvailableModels = result.available_models ?? []
  const nextModel = resolveSelectedModel(profile.model, nextAvailableModels)
  const hasSelectedModel = nextModel.trim().length > 0
  return {
    ...profile,
    model: nextModel,
    hasApiKey: Boolean(profile.apiKey.trim()) || profile.hasApiKey,
    availableModels: nextAvailableModels,
    status: result.success && hasSelectedModel ? 'connected' : 'error',
    statusMessage: result.success && !hasSelectedModel ? '连接成功，但请先选择模型' : result.message,
    lastTestedAt: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
  }
}

export function SettingsView({
  courseId,
  modelProfile,
  theme,
  uiFont,
  uiFontSize,
  onModelProfileChange,
  onThemeChange,
  onUiFontChange,
  onUiFontSizeChange,
  authUser,
  onAuthUserChange,
  onLogout,
}: SettingsViewProps) {
  const [draft, setDraft] = useState(modelProfile)
  const [isApiKeyVisible, setIsApiKeyVisible] = useState(false)
  const [embeddingDraft, setEmbeddingDraft] = useState(defaultEmbeddingProfile)
  const [knowledgeStatus, setKnowledgeStatus] = useState<KnowledgeBaseStatus | null>(null)
  const [embeddingAction, setEmbeddingAction] = useState<'idle' | 'saving' | 'testing' | 'indexing'>('idle')
  const [mcpServers, setMcpServers] = useState<McpServer[]>([])
  const [mcpDraft, setMcpDraft] = useState({
    id: '', name: '', transport: 'http' as McpServer['transport'], endpoint: '', command: '', args: '', tools: '',
  })
  const [mcpAction, setMcpAction] = useState<'idle' | 'saving' | 'discovering'>('idle')
  const [mcpMessage, setMcpMessage] = useState('')
  const [bilibiliStatus, setBilibiliStatus] = useState<BilibiliCredentialStatus | null>(null)
  const [isBilibiliDialogOpen, setIsBilibiliDialogOpen] = useState(false)
  const [accountProfileDraft, setAccountProfileDraft] = useState({
    displayName: authUser?.displayName ?? '',
    avatarUrl: '',
    gender: '',
    age: '',
    signature: '',
  })
  const [accountProfileAction, setAccountProfileAction] = useState<'idle' | 'loading' | 'saving' | 'uploading'>('loading')
  const [accountProfileMessage, setAccountProfileMessage] = useState('')
  const [userProfilePrompt, setUserProfilePrompt] = useState('')
  const [userProfileUpdatedAt, setUserProfileUpdatedAt] = useState('')
  const [userProfileAction, setUserProfileAction] = useState<'idle' | 'loading' | 'saving'>('loading')
  const [userProfileMessage, setUserProfileMessage] = useState('')
  const draftRef = useRef(draft)

  useEffect(() => {
    setDraft(modelProfile)
  }, [modelProfile])

  useEffect(() => {
    draftRef.current = draft
  }, [draft])

  useEffect(() => {
    let isCancelled = false
    void Promise.all([getEmbeddingProfile(), getKnowledgeBaseStatus(courseId)])
      .then(([embedding, knowledge]) => {
        if (isCancelled) return
        setEmbeddingDraft({
          ...embedding,
          indexedChunks: knowledge.embedding.indexedChunks,
          totalChunks: knowledge.embedding.totalChunks,
          dimension: knowledge.embedding.dimension || embedding.dimension,
        })
        setKnowledgeStatus(knowledge)
      })
      .catch((error) => {
        if (isCancelled) return
        setEmbeddingDraft((current) => ({
          ...current,
          status: 'unavailable',
          message: error instanceof Error ? error.message : '无法读取知识库状态。',
        }))
      })
    return () => {
      isCancelled = true
    }
  }, [courseId])

  useEffect(() => {
    let isCancelled = false
    void listMcpServers()
      .then((servers) => {
        if (!isCancelled) setMcpServers(servers)
      })
      .catch((error) => {
        if (!isCancelled) setMcpMessage(error instanceof Error ? error.message : '无法读取 MCP 服务。')
      })
    return () => {
      isCancelled = true
    }
  }, [])

  function refreshBilibiliStatus() {
    if (isDemoMode) return
    void getBilibiliCredentialStatus()
      .then((status) => setBilibiliStatus(status))
      .catch(() => setBilibiliStatus(null))
  }

  useEffect(() => {
    refreshBilibiliStatus()
  }, [])

  useEffect(() => {
    let isCancelled = false
    setAccountProfileAction('loading')
    void getAccountProfile()
      .then((profile) => {
        if (isCancelled) return
        setAccountProfileDraft({
          displayName: profile.displayName || profile.email,
          avatarUrl: profile.avatarUrl,
          gender: profile.gender,
          age: profile.age === null ? '' : String(profile.age),
          signature: profile.signature,
        })
        setAccountProfileMessage('')
      })
      .catch((error) => {
        if (!isCancelled) setAccountProfileMessage(error instanceof Error ? error.message : '无法读取个人信息。')
      })
      .finally(() => {
        if (!isCancelled) setAccountProfileAction('idle')
      })
    return () => {
      isCancelled = true
    }
  }, [])

  useEffect(() => {
    let isCancelled = false
    setUserProfileAction('loading')
    void getUserProfilePrompt()
      .then((profile) => {
        if (isCancelled) return
        setUserProfilePrompt(profile.content)
        setUserProfileUpdatedAt(profile.updatedAt)
        setUserProfileMessage('')
      })
      .catch((error) => {
        if (!isCancelled) setUserProfileMessage(error instanceof Error ? error.message : '无法读取用户自画像。')
      })
      .finally(() => {
        if (!isCancelled) setUserProfileAction('idle')
      })
    return () => {
      isCancelled = true
    }
  }, [])

  const draftProvider = draft.provider
  const draftBaseUrl = draft.baseUrl
  const draftApiKey = draft.apiKey
  const draftHasApiKey = draft.hasApiKey

  useEffect(() => {
    if (draftProvider !== 'custom') return

    const baseUrl = draftBaseUrl.trim()
    const apiKey = draftApiKey.trim()
    if (!baseUrl || (!apiKey && !draftHasApiKey)) return

    let isCancelled = false
    const timer = window.setTimeout(() => {
      const sourceProfile = { ...draftRef.current, baseUrl, apiKey }
      const loadingProfile: ModelProfile = {
        ...sourceProfile,
        status: 'testing',
        statusMessage: '正在读取可用模型',
      }
      setDraft(loadingProfile)
      onModelProfileChange(loadingProfile)

      void requestAvailableModels(sourceProfile)
        .then((result) => {
          if (isCancelled) return
          const nextProfile = toProfileWithAvailableModels(sourceProfile, result)
          setDraft(nextProfile)
          onModelProfileChange(nextProfile)
        })
        .catch(() => {
          if (isCancelled) return
          const unavailableProfile: ModelProfile = {
            ...sourceProfile,
            status: 'error',
            statusMessage: '无法读取可用模型，请检查本地服务或模型接口',
          }
          setDraft(unavailableProfile)
          onModelProfileChange(unavailableProfile)
        })
    }, 650)

    return () => {
      isCancelled = true
      window.clearTimeout(timer)
    }
  }, [draftProvider, draftBaseUrl, draftApiKey, draftHasApiKey, onModelProfileChange])

  function updateDraft<K extends keyof ModelProfile>(key: K, value: ModelProfile[K]) {
    setDraft((current) => {
      const nextProfile = { ...current, [key]: value }
      if (key === 'baseUrl' || key === 'apiKey') {
        return {
          ...nextProfile,
          hasApiKey: key === 'apiKey' ? Boolean(String(value).trim()) || current.hasApiKey : current.hasApiKey,
          availableModels: undefined,
          status: 'unconfigured',
          statusMessage: '',
          lastTestedAt: undefined,
        }
      }
      return nextProfile
    })
  }

  function selectProvider(provider: ModelProvider) {
    const preset = getProviderPreset(provider)
    setDraft((current) => ({
      ...current,
      provider,
      baseUrl: preset.baseUrl,
      model: preset.model,
      hasApiKey: current.hasApiKey,
      availableModels: undefined,
      supportsVision: preset.supportsVision,
      status: 'unconfigured',
      statusMessage: '',
      lastTestedAt: undefined,
    }))
  }

  async function saveProfile() {
    if (!draft.baseUrl.trim() || !draft.model.trim() || (!draft.apiKey.trim() && !draft.hasApiKey)) {
      const incompleteProfile: ModelProfile = {
        ...draft,
        status: 'error',
        statusMessage: '请先填写 Base URL、模型名和 API Key',
      }
      setDraft(incompleteProfile)
      onModelProfileChange(incompleteProfile)
      return
    }

    const savingProfile: ModelProfile = {
      ...draft,
      status: 'testing',
      statusMessage: '正在保存配置',
    }
    setDraft(savingProfile)
    onModelProfileChange(savingProfile)

    try {
      const runtimeModel = await saveRuntimeModel({
        baseUrl: draft.baseUrl,
        apiKey: draft.apiKey,
        model: draft.model,
      })
      const nextProfile: ModelProfile = {
        ...toRuntimeModelProfile(runtimeModel),
        supportsVision: draft.supportsVision,
        status: 'saved',
        statusMessage: '配置已保存到本机',
        lastTestedAt: draft.lastTestedAt,
      }
      setDraft(nextProfile)
      onModelProfileChange(nextProfile)
    } catch (error) {
      const failedProfile: ModelProfile = {
        ...draft,
        status: 'error',
        statusMessage: error instanceof Error ? error.message : '配置保存失败',
      }
      setDraft(failedProfile)
      onModelProfileChange(failedProfile)
    }
  }

  async function testConnection() {
    if (!draft.baseUrl.trim() || (!draft.apiKey.trim() && !draft.hasApiKey)) {
      const incompleteProfile: ModelProfile = {
        ...draft,
        status: 'error',
        statusMessage: '请先填写 Base URL 和 API Key',
      }
      setDraft(incompleteProfile)
      onModelProfileChange(incompleteProfile)
      return
    }

    const testingProfile: ModelProfile = {
      ...draft,
      status: 'testing',
      statusMessage: '正在连接模型服务',
    }
    setDraft(testingProfile)
    onModelProfileChange(testingProfile)

    try {
      const result = await requestAvailableModels(draft)
      const nextProfile = toProfileWithAvailableModels(draft, result)
      setDraft(nextProfile)
      onModelProfileChange(nextProfile)
    } catch {
      const unavailableProfile: ModelProfile = {
        ...draft,
        status: 'error',
        statusMessage: '本地服务未启动，无法完成连接测试',
      }
      setDraft(unavailableProfile)
      onModelProfileChange(unavailableProfile)
    }
  }

  async function saveEmbeddingSettings() {
    setEmbeddingAction('saving')
    try {
      const profile = await saveEmbeddingProfile(embeddingDraft)
      setEmbeddingDraft(profile)
    } catch (error) {
      setEmbeddingDraft((current) => ({
        ...current,
        status: 'unavailable',
        message: error instanceof Error ? error.message : 'Embedding 配置保存失败。',
      }))
    } finally {
      setEmbeddingAction('idle')
    }
  }

  async function testEmbeddingSettings() {
    setEmbeddingAction('testing')
    try {
      await saveEmbeddingProfile(embeddingDraft)
      const profile = await testEmbeddingProfile()
      setEmbeddingDraft(profile)
    } catch (error) {
      setEmbeddingDraft((current) => ({
        ...current,
        status: 'unavailable',
        message: error instanceof Error ? error.message : 'Embedding 连接测试失败。',
      }))
    } finally {
      setEmbeddingAction('idle')
    }
  }

  async function rebuildEmbeddingIndex() {
    setEmbeddingAction('indexing')
    setEmbeddingDraft((current) => ({ ...current, status: 'indexing', message: '正在重建资料向量索引。' }))
    try {
      await saveEmbeddingProfile(embeddingDraft)
      const profile = await rebuildKnowledgeEmbeddings(courseId)
      setEmbeddingDraft(profile)
      setKnowledgeStatus(await getKnowledgeBaseStatus(courseId))
    } catch (error) {
      setEmbeddingDraft((current) => ({
        ...current,
        status: 'unavailable',
        message: error instanceof Error ? error.message : '向量索引重建失败。',
      }))
    } finally {
      setEmbeddingAction('idle')
    }
  }

  function selectMcpServer(serverId: string) {
    const server = mcpServers.find((item) => item.id === serverId)
    setMcpDraft(server
      ? {
          id: server.id,
          name: server.name,
          transport: server.transport,
          endpoint: server.endpoint,
          command: server.command,
          args: server.args.join(' '),
          tools: server.allowedTools.join(', '),
        }
      : { id: '', name: '', transport: 'http', endpoint: '', command: '', args: '', tools: '' })
    setMcpMessage('')
  }

  async function saveMcpSettings() {
    const allowedTools = mcpDraft.tools.split(',').map((item) => item.trim()).filter(Boolean)
    const hasConnection = mcpDraft.transport === 'stdio' ? mcpDraft.command.trim() : mcpDraft.endpoint.trim()
    if (!mcpDraft.name.trim() || !hasConnection || !allowedTools.length) {
      setMcpMessage('请填写服务名称、连接配置和至少一个工具名。')
      return
    }
    setMcpAction('saving')
    setMcpMessage('')
    try {
      const saved = await saveMcpServer({
        id: mcpDraft.id || undefined,
        name: mcpDraft.name,
        endpoint: mcpDraft.endpoint,
        transport: mcpDraft.transport,
        command: mcpDraft.command,
        args: mcpDraft.args.split(/\s+/).filter(Boolean),
        allowedTools,
      })
      setMcpServers((current) => [...current.filter((item) => item.id !== saved.id), saved])
      selectMcpServerFromValue(saved)
      setMcpMessage('MCP 服务配置已保存。')
    } catch (error) {
      setMcpMessage(error instanceof Error ? error.message : 'MCP 服务配置保存失败。')
    } finally {
      setMcpAction('idle')
    }
  }

  function selectMcpServerFromValue(server: McpServer) {
    setMcpDraft({
      id: server.id,
      name: server.name,
      transport: server.transport,
      endpoint: server.endpoint,
      command: server.command,
      args: server.args.join(' '),
      tools: server.allowedTools.join(', '),
    })
  }

  async function discoverMcpTools() {
    if (!mcpDraft.id) {
      setMcpMessage('请先保存 MCP 配置。')
      return
    }
    setMcpAction('discovering')
    setMcpMessage('')
    try {
      const discovered = await discoverMcpServer(mcpDraft.id)
      setMcpServers((current) => [...current.filter((item) => item.id !== discovered.id), discovered])
      selectMcpServerFromValue(discovered)
      setMcpMessage(`连接成功，发现 ${discovered.tools.length} 个工具。`)
    } catch (error) {
      setMcpMessage(error instanceof Error ? error.message : 'MCP 工具发现失败。')
    } finally {
      setMcpAction('idle')
    }
  }

  function updateAccountProfileDraft(key: keyof typeof accountProfileDraft, value: string) {
    setAccountProfileDraft((current) => ({ ...current, [key]: value }))
  }

  async function saveAccountProfileSettings() {
    const displayName = accountProfileDraft.displayName.trim()
    if (!displayName) {
      setAccountProfileMessage('用户名不能为空。')
      return
    }
    const ageText = accountProfileDraft.age.trim()
    const age = ageText ? Number(ageText) : null
    if (ageText && (age === null || !Number.isInteger(age) || age < 0 || age > 150)) {
      setAccountProfileMessage('年龄需要填写 0 到 150 之间的整数。')
      return
    }
    setAccountProfileAction('saving')
    setAccountProfileMessage('')
    try {
      const profile = await saveAccountProfile({
        displayName,
        gender: accountProfileDraft.gender,
        age,
        signature: accountProfileDraft.signature,
      })
      setAccountProfileDraft({
        displayName: profile.displayName || profile.email,
        avatarUrl: profile.avatarUrl,
        gender: profile.gender,
        age: profile.age === null ? '' : String(profile.age),
        signature: profile.signature,
      })
      onAuthUserChange({
        id: profile.id,
        email: profile.email,
        displayName: profile.displayName || profile.email,
        role: profile.role,
        avatarUrl: profile.avatarUrl,
      })
      setAccountProfileMessage('个人信息已保存。')
    } catch (error) {
      setAccountProfileMessage(error instanceof Error ? error.message : '个人信息保存失败。')
    } finally {
      setAccountProfileAction('idle')
    }
  }

  async function handleAvatarFile(file: File | undefined) {
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setAccountProfileMessage('请选择图片文件。')
      return
    }
    if (file.size > 2 * 1024 * 1024) {
      setAccountProfileMessage('头像图片不能超过 2 MB。')
      return
    }
    setAccountProfileAction('uploading')
    setAccountProfileMessage('')
    try {
      const profile = await uploadAccountAvatar(file)
      setAccountProfileDraft((current) => ({ ...current, avatarUrl: profile.avatarUrl }))
      onAuthUserChange({
        id: profile.id,
        email: profile.email,
        displayName: profile.displayName || profile.email,
        role: profile.role,
        avatarUrl: profile.avatarUrl,
      })
      setAccountProfileMessage('头像已上传并保存到数据库。')
    } catch (error) {
      setAccountProfileMessage(error instanceof Error ? error.message : '头像上传失败。')
    } finally {
      setAccountProfileAction('idle')
    }
  }

  async function removeAccountAvatar() {
    setAccountProfileAction('uploading')
    setAccountProfileMessage('')
    try {
      const profile = await deleteAccountAvatar()
      setAccountProfileDraft((current) => ({ ...current, avatarUrl: profile.avatarUrl }))
      onAuthUserChange({
        id: profile.id,
        email: profile.email,
        displayName: profile.displayName || profile.email,
        role: profile.role,
        avatarUrl: profile.avatarUrl,
      })
      setAccountProfileMessage('头像已删除。')
    } catch (error) {
      setAccountProfileMessage(error instanceof Error ? error.message : '头像删除失败。')
    } finally {
      setAccountProfileAction('idle')
    }
  }

  const accountAvatarInitial = (accountProfileDraft.displayName || authUser?.email || '用').trim().slice(0, 1).toUpperCase()

  async function saveUserProfileSettings() {
    if (userProfilePrompt.length > userProfilePromptMaxLength) {
      setUserProfileMessage(`用户自画像不能超过 ${userProfilePromptMaxLength} 字。`)
      return
    }
    setUserProfileAction('saving')
    setUserProfileMessage('')
    try {
      const profile = await saveUserProfilePrompt(userProfilePrompt)
      setUserProfilePrompt(profile.content)
      setUserProfileUpdatedAt(profile.updatedAt)
      setUserProfileMessage('用户自画像已保存，并会对所有课程生效。')
    } catch (error) {
      setUserProfileMessage(error instanceof Error ? error.message : '用户自画像保存失败。')
    } finally {
      setUserProfileAction('idle')
    }
  }

  const currentStatus = statusContent(draft)
  const StatusIcon = currentStatus.icon
  const availableModels = draft.availableModels ?? []
  const hasAvailableModels = draft.provider === 'custom' && availableModels.length > 0
  const selectedModelValue = availableModels.includes(draft.model) ? draft.model : ''
  const selectedUiFont = uiFontOptions.find((font) => font.id === uiFont) ?? uiFontOptions[0]
  const selectedUiFontSize = uiFontSizeOptions.includes(uiFontSize) ? uiFontSize : 100
  const embeddingTone = embeddingDraft.status === 'ready'
    ? 'success'
    : embeddingDraft.status === 'indexing'
      ? 'testing'
      : embeddingDraft.status === 'unavailable'
        ? 'error'
        : 'neutral'
  const isEmbeddingBusy = embeddingAction !== 'idle'

  return (
    <div className="module-page settings-page">
      <section className="page-heading-row">
        <div>
          <p className="page-kicker"><Sparkles size={15} /> 本机配置，仅在需要时发送至模型服务</p>
          <h1>设置</h1>
          <p>选择模型、保存连接参数，并为 AI 伴学启用适合你的能力。</p>
        </div>
        <div className={`connection-status ${currentStatus.tone}`}>
          <StatusIcon size={16} />
          <span>{currentStatus.label}</span>
        </div>
      </section>

      <section className="settings-panel account-settings-panel">
        <header className="settings-panel-heading">
          <div className="account-avatar-preview" aria-hidden="true">
            {accountProfileDraft.avatarUrl ? <img src={accountProfileDraft.avatarUrl} alt="" /> : <span>{accountAvatarInitial}</span>}
          </div>
          <div>
            <h2>个人信息</h2>
            <p>{authUser?.email || '当前登录用户'} · 这些资料会长期保存到账号数据库。</p>
          </div>
        </header>

        <div className="account-profile-grid">
          <label className="settings-field">
            <span>用户名</span>
            <input
              value={accountProfileDraft.displayName}
              maxLength={40}
              disabled={accountProfileAction === 'loading'}
              onChange={(event) => updateAccountProfileDraft('displayName', event.target.value)}
            />
          </label>
          <label className="settings-field">
            <span>性别</span>
            <input
              value={accountProfileDraft.gender}
              maxLength={20}
              placeholder="例如：女 / 男 / 保密"
              disabled={accountProfileAction === 'loading'}
              onChange={(event) => updateAccountProfileDraft('gender', event.target.value)}
            />
          </label>
          <label className="settings-field">
            <span>年龄</span>
            <input
              type="number"
              min="0"
              max="150"
              step="1"
              value={accountProfileDraft.age}
              placeholder="可选"
              disabled={accountProfileAction === 'loading'}
              onChange={(event) => updateAccountProfileDraft('age', event.target.value)}
            />
          </label>
          <div className="settings-field settings-field-wide">
            <span>头像</span>
            <div className="account-avatar-upload">
              <label className="secondary-button account-avatar-upload-button">
                <Upload size={16} />
                {accountProfileAction === 'uploading' ? '处理中' : accountProfileDraft.avatarUrl ? '更换图片' : '上传图片'}
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/gif,image/webp"
                  disabled={accountProfileAction !== 'idle'}
                  onChange={(event) => {
                    void handleAvatarFile(event.target.files?.[0])
                    event.target.value = ''
                  }}
                />
              </label>
              {accountProfileDraft.avatarUrl && (
                <button className="secondary-button" type="button" disabled={accountProfileAction !== 'idle'} onClick={() => void removeAccountAvatar()}>
                  <Trash2 size={16} /> 删除头像
                </button>
              )}
              <small>支持 JPG、PNG、GIF、WebP，最大 2 MB；上传后直接保存到账号数据库。</small>
            </div>
          </div>
          <label className="settings-field settings-field-wide">
            <span>个性签名</span>
            <textarea
              className="account-signature-textarea"
              value={accountProfileDraft.signature}
              maxLength={200}
              placeholder="写一句介绍自己或当前学习目标的话"
              disabled={accountProfileAction === 'loading'}
              onChange={(event) => updateAccountProfileDraft('signature', event.target.value)}
            />
          </label>
        </div>

        <div className="settings-actions account-profile-actions">
          <button className="primary-button" type="button" disabled={accountProfileAction !== 'idle'} onClick={saveAccountProfileSettings}>
            <Save size={16} /> {accountProfileAction === 'saving' ? '保存中' : '保存个人信息'}
          </button>
          {onLogout && (
            <button className="secondary-button" type="button" onClick={onLogout}>
              <LogOut size={16} /> 退出登录
            </button>
          )}
          {accountProfileMessage && <span className="settings-message">{accountProfileMessage}</span>}
        </div>
      </section>

      <div className="settings-layout">
        <section className="settings-panel model-settings-panel">
          <header className="settings-panel-heading">
            <div className="settings-heading-icon"><Bot size={19} /></div>
            <div>
              <h2>AI 模型设置</h2>
              <p>选择预设厂商，或配置 OpenAI 兼容接口。</p>
            </div>
          </header>

          <div className="provider-grid" role="radiogroup" aria-label="模型厂商">
            {providerPresets.map((provider) => (
              <button
                className={`provider-option ${draft.provider === provider.id ? 'is-selected' : ''}`}
                key={provider.id}
                type="button"
                role="radio"
                aria-checked={draft.provider === provider.id}
                onClick={() => selectProvider(provider.id)}
              >
                <span>{provider.label}</span>
                <small>{provider.description}</small>
              </button>
            ))}
          </div>

          <div className="model-form-grid">
            <label className="settings-field settings-field-wide">
              <span>Base URL</span>
              <div className="field-with-icon">
                <Link2 size={16} />
                <input
                  value={draft.baseUrl}
                  placeholder="https://example.com/v1"
                  autoComplete="url"
                  onChange={(event) => updateDraft('baseUrl', event.target.value)}
                />
              </div>
            </label>

            <label className="settings-field">
              <span>模型名</span>
              {hasAvailableModels ? (
                <select value={selectedModelValue} onChange={(event) => updateDraft('model', event.target.value)}>
                  {!selectedModelValue && <option value="">请选择模型</option>}
                  {availableModels.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  value={draft.model}
                  placeholder="例如：gpt-4.1-mini"
                  onChange={(event) => updateDraft('model', event.target.value)}
                />
              )}
            </label>

            <label className="settings-field">
              <span>API Key</span>
              <div className="field-with-icon">
                <KeyRound size={16} />
                <input
                  type={isApiKeyVisible ? 'text' : 'password'}
                  value={draft.apiKey}
                  placeholder={draft.hasApiKey ? '已保存到本机，留空继续使用' : '仅保存在本机'}
                  autoComplete="off"
                  onChange={(event) => updateDraft('apiKey', event.target.value)}
                />
                <button
                  type="button"
                  aria-label={isApiKeyVisible ? '隐藏 API Key' : '显示 API Key'}
                  onClick={() => setIsApiKeyVisible((current) => !current)}
                >
                  {isApiKeyVisible ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>
          </div>

          <label className="vision-toggle">
            <input
              type="checkbox"
              checked={draft.supportsVision}
              onChange={(event) => updateDraft('supportsVision', event.target.checked)}
            />
            <span className="toggle-track" aria-hidden="true"><i></i></span>
            <span>
              <strong>启用图片理解</strong>
              <small>用于分析题目截图、图表和课件中的示意图。</small>
            </span>
          </label>

          <div className="settings-actions">
            <button className="secondary-button" type="button" onClick={testConnection}>
              {draft.status === 'testing' ? <LoaderCircle className="is-spinning" size={16} /> : <PlugZap size={16} />}
              测试连接
            </button>
            <button className="primary-button" type="button" onClick={saveProfile}>
              <Save size={16} /> 保存配置
            </button>
          </div>

          <div className="knowledge-settings">
            <header className="settings-panel-heading">
              <div className="settings-heading-icon secondary"><Database size={19} /></div>
              <div>
                <h2>本地知识库</h2>
                <p>资料分块、学习记录与长期记忆保存在本机。</p>
              </div>
            </header>

            <label className="vision-toggle">
              <input
                type="checkbox"
                checked={embeddingDraft.enabled}
                onChange={(event) => setEmbeddingDraft((current) => ({
                  ...current,
                  enabled: event.target.checked,
                  status: event.target.checked ? 'unavailable' : 'disabled',
                  message: event.target.checked ? '保存后可检测 Embedding 服务。' : 'Embedding 已关闭，当前使用关键词检索。',
                }))}
              />
              <span className="toggle-track" aria-hidden="true"><i></i></span>
              <span>
                <strong>启用语义检索</strong>
                <small>关闭后仍保留资料分块、对话记忆和关键词检索。</small>
              </span>
            </label>

            <div className="model-form-grid knowledge-form-grid">
              <label className="settings-field settings-field-wide">
                <span>Ollama Base URL</span>
                <div className="field-with-icon">
                  <Link2 size={16} />
                  <input
                    value={embeddingDraft.baseUrl}
                    disabled={!embeddingDraft.enabled || isEmbeddingBusy}
                    onChange={(event) => setEmbeddingDraft((current) => ({ ...current, baseUrl: event.target.value }))}
                  />
                </div>
              </label>
              <label className="settings-field">
                <span>Embedding 模型</span>
                <input
                  value={embeddingDraft.model}
                  disabled={!embeddingDraft.enabled || isEmbeddingBusy}
                  onChange={(event) => setEmbeddingDraft((current) => ({ ...current, model: event.target.value }))}
                />
              </label>
              <div className={`connection-status ${embeddingTone}`}>
                {embeddingDraft.status === 'ready' ? <CheckCircle2 size={16} /> : <CircleAlert size={16} />}
                <span>{embeddingDraft.message}</span>
              </div>
            </div>

            <dl className="knowledge-metrics">
              <div><dt>资料</dt><dd>{knowledgeStatus?.materials ?? 0}</dd></div>
              <div><dt>分块</dt><dd>{knowledgeStatus?.chunks ?? embeddingDraft.totalChunks}</dd></div>
              <div><dt>对话</dt><dd>{knowledgeStatus?.chatTurns ?? 0}</dd></div>
              <div><dt>记忆</dt><dd>{knowledgeStatus?.memories ?? 0}</dd></div>
              <div><dt>向量</dt><dd>{embeddingDraft.indexedChunks}/{embeddingDraft.totalChunks}</dd></div>
            </dl>

            <div className="settings-actions">
              <button
                className="secondary-button"
                type="button"
                disabled={isEmbeddingBusy || !embeddingDraft.enabled}
                onClick={testEmbeddingSettings}
              >
                {embeddingAction === 'testing' ? <LoaderCircle className="is-spinning" size={16} /> : <PlugZap size={16} />}
                检测服务
              </button>
              <button
                className="secondary-button"
                type="button"
                disabled={isEmbeddingBusy || !embeddingDraft.enabled}
                onClick={rebuildEmbeddingIndex}
              >
                <RefreshCw className={embeddingAction === 'indexing' ? 'is-spinning' : ''} size={16} /> 重建索引
              </button>
              <button className="primary-button" type="button" disabled={isEmbeddingBusy} onClick={saveEmbeddingSettings}>
                <Save size={16} /> 保存知识库配置
              </button>
            </div>
          </div>

          <div className="knowledge-settings">
            <header className="settings-panel-heading">
              <div className="settings-heading-icon tertiary"><PlugZap size={19} /></div>
              <div>
                <h2>MCP 服务</h2>
                <p>配置外部资料解析服务和允许调用的工具。</p>
              </div>
              {!isDemoMode && (
                <button
                  className={`bilibili-credential-badge ${
                    bilibiliStatus?.configured ? 'is-ok' : bilibiliStatus?.source === 'global_config' ? 'is-warn' : 'is-bad'
                  }`}
                  type="button"
                  onClick={() => setIsBilibiliDialogOpen(true)}
                >
                  {bilibiliStatus?.configured
                    ? <><CheckCircle2 size={14} /> B站已配置</>
                    : bilibiliStatus?.source === 'global_config'
                      ? <><CircleAlert size={14} /> B站凭据待更新</>
                      : bilibiliStatus
                        ? <><CircleAlert size={14} /> B站未配置</>
                        : <><CircleAlert size={14} /> B站状态未知</>}
                </button>
              )}
            </header>
            <div className="model-form-grid knowledge-form-grid">
              <label className="settings-field">
                <span>配置</span>
                <select value={mcpDraft.id} onChange={(event) => selectMcpServer(event.target.value)}>
                  <option value="">新增 MCP 服务</option>
                  {mcpServers.map((server) => <option key={server.id} value={server.id}>{server.name}</option>)}
                </select>
              </label>
              <label className="settings-field">
                <span>服务名称</span>
                <input value={mcpDraft.name} onChange={(event) => setMcpDraft((current) => ({ ...current, name: event.target.value }))} />
              </label>
              <label className="settings-field">
                <span>传输方式</span>
                <select
                  value={mcpDraft.transport}
                  onChange={(event) => setMcpDraft((current) => ({ ...current, transport: event.target.value as McpServer['transport'] }))}
                >
                  <option value="http">Streamable HTTP</option>
                  <option value="stdio">本机 stdio</option>
                </select>
              </label>
              {mcpDraft.transport === 'http' ? (
                <label className="settings-field settings-field-wide">
                  <span>Streamable HTTP Endpoint</span>
                  <div className="field-with-icon">
                    <Link2 size={16} />
                    <input
                      value={mcpDraft.endpoint}
                      placeholder="https://mcp.example.com/mcp"
                      autoComplete="url"
                      onChange={(event) => setMcpDraft((current) => ({ ...current, endpoint: event.target.value }))}
                    />
                  </div>
                </label>
              ) : (
                <>
                  <label className="settings-field">
                    <span>启动命令</span>
                    <input value={mcpDraft.command} onChange={(event) => setMcpDraft((current) => ({ ...current, command: event.target.value }))} />
                  </label>
                  <label className="settings-field">
                    <span>启动参数</span>
                    <input value={mcpDraft.args} onChange={(event) => setMcpDraft((current) => ({ ...current, args: event.target.value }))} />
                  </label>
                </>
              )}
              <label className="settings-field settings-field-wide">
                <span>工具白名单</span>
                <input
                  value={mcpDraft.tools}
                  placeholder="fetch_url, parse_video"
                  onChange={(event) => setMcpDraft((current) => ({ ...current, tools: event.target.value }))}
                />
              </label>
            </div>
            {mcpMessage && <p className="embedding-inline-note">{mcpMessage}</p>}
            <div className="settings-actions">
              <button className="secondary-button" type="button" disabled={mcpAction !== 'idle' || !mcpDraft.id} onClick={discoverMcpTools}>
                <RefreshCw className={mcpAction === 'discovering' ? 'is-spinning' : ''} size={16} />
                检测工具
              </button>
              <button className="primary-button" type="button" disabled={mcpAction === 'saving'} onClick={saveMcpSettings}>
                {mcpAction === 'saving' ? <LoaderCircle className="is-spinning" size={16} /> : <Save size={16} />}
                保存 MCP 配置
              </button>
            </div>
          </div>
        </section>

        <aside className="settings-side">
          <section className="settings-panel profile-summary-panel">
            <header className="settings-panel-heading">
              <div className="settings-heading-icon secondary"><Sparkles size={19} /></div>
              <div>
                <h2>当前 AI 档案</h2>
                <p>会用于资料分析、摸底和伴学对话。</p>
              </div>
            </header>
            <dl className="profile-summary-list">
              <div>
                <dt>厂商</dt>
                <dd>{formatProviderName(draft.provider)}</dd>
              </div>
              <div>
                <dt>模型</dt>
                <dd>{draft.model || '未设置'}</dd>
              </div>
              <div>
                <dt>图像能力</dt>
                <dd>{draft.supportsVision ? '已启用' : '未启用'}</dd>
              </div>
              <div>
                <dt>API Key</dt>
                <dd>{draft.hasApiKey ? '已保存到本机' : '未保存'}</dd>
              </div>
              <div>
                <dt>最近测试</dt>
                <dd>{draft.lastTestedAt ?? '尚未测试'}</dd>
              </div>
            </dl>
          </section>

          <section className="settings-panel appearance-panel">
            <header className="settings-panel-heading">
              <div className="settings-heading-icon tertiary"><Sun size={19} /></div>
              <div>
                <h2>界面外观</h2>
                <p>背景会随浅色和深色模式自动切换。</p>
              </div>
            </header>
            <div className="theme-selector">
              <button
                className={theme === 'light' ? 'is-selected' : ''}
                type="button"
                onClick={() => onThemeChange('light')}
              >
                <Sun size={17} /> 浅色模式
              </button>
              <button
                className={theme === 'dark' ? 'is-selected' : ''}
                type="button"
                onClick={() => onThemeChange('dark')}
              >
                <Moon size={17} /> 深色模式
              </button>
            </div>
            <label className="settings-field appearance-font-field">
              <span>界面字体</span>
              <select value={uiFont} onChange={(event) => onUiFontChange(event.target.value as UiFont)}>
                {uiFontOptions.map((font) => (
                  <option key={font.id} value={font.id}>
                    {font.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="font-size-control">
              <span>
                字体大小
                <b>{selectedUiFontSize}%</b>
              </span>
              <input
                type="range"
                min={uiFontSizeOptions[0]}
                max={uiFontSizeOptions[uiFontSizeOptions.length - 1]}
                step={5}
                value={selectedUiFontSize}
                aria-label="界面字体大小"
                onChange={(event) => onUiFontSizeChange(Number(event.target.value) as UiFontSize)}
              />
              <span className="font-size-ticks" aria-hidden="true">
                <small>小</small>
                <small>标准</small>
                <small>大</small>
              </span>
            </label>
            <p className="font-preview" style={{ fontFamily: selectedUiFont.previewFamily }}>
              期末粥加速器 · 公式 / 笔记 / 错题
            </p>
          </section>

          <section className="settings-panel user-profile-panel">
            <header className="settings-panel-heading">
              <div className="settings-heading-icon secondary"><UserRound size={19} /></div>
              <div>
                <h2>用户自画像</h2>
                <p>补充你的长期学习偏好，对所有课程生效。</p>
              </div>
            </header>
            <label className="settings-field">
              <span>全局 Prompt</span>
              <textarea
                className="user-profile-textarea"
                value={userProfilePrompt}
                maxLength={userProfilePromptMaxLength}
                disabled={userProfileAction !== 'idle'}
                placeholder="例如：我基础较弱，讲解时先解释公式含义，再给步骤；做题时不要直接跳到答案。"
                onChange={(event) => setUserProfilePrompt(event.target.value)}
              />
            </label>
            <div className="user-profile-meta">
              <span>{userProfilePrompt.length}/{userProfilePromptMaxLength}</span>
              <span>{userProfileUpdatedAt ? `最近保存：${userProfileUpdatedAt}` : '尚未保存'}</span>
            </div>
            {userProfileMessage && <p className="embedding-inline-note">{userProfileMessage}</p>}
            <div className="settings-actions">
              <button
                className="primary-button"
                type="button"
                disabled={userProfileAction !== 'idle' || userProfilePrompt.length > userProfilePromptMaxLength}
                onClick={saveUserProfileSettings}
              >
                {userProfileAction === 'saving' ? <LoaderCircle className="is-spinning" size={16} /> : <Save size={16} />}
                保存自画像
              </button>
            </div>
          </section>
        </aside>
      </div>
      {isBilibiliDialogOpen && (
        <BilibiliCredentialDialog
          status={bilibiliStatus}
          onClose={() => setIsBilibiliDialogOpen(false)}
          onSaved={refreshBilibiliStatus}
        />
      )}
    </div>
  )
}
