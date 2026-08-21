/**
 * 登录/注册页（阶段1）。
 * 无会话时由 App.tsx 整页渲染；登录成功后回调 onAuthed 拉起工作台。
 * 演示模式下不渲染此页（demo 无后端认证）。
 */
import { type FormEvent, useState } from 'react'
import { GraduationCap, LoaderCircle, Sparkles } from 'lucide-react'
import { loginWithPassword, registerAccount } from '../auth'

type LoginPageProps = {
  onAuthed: () => void
}

type AuthMode = 'login' | 'register'

export function LoginPage({ onAuthed }: LoginPageProps) {
  const [mode, setMode] = useState<AuthMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (isSubmitting) return
    setError('')
    if (!email.trim()) return setError('请输入邮箱')
    if (password.length < 8) return setError('密码至少需要 8 位')
    if (mode === 'register' && !displayName.trim()) return setError('请输入昵称')
    setIsSubmitting(true)
    try {
      if (mode === 'login') {
        await loginWithPassword(email.trim(), password)
      } else {
        await registerAccount(email.trim(), password, displayName.trim())
      }
      onAuthed()
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '认证失败，请稍后重试')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <div className="modal-icon"><GraduationCap size={22} /></div>
          <div>
            <h1>期末粥++</h1>
            <p>期末周 AI 学习工作台 · 校园版</p>
          </div>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          {mode === 'register' && (
            <label>
              昵称
              <input
                type="text"
                value={displayName}
                maxLength={40}
                placeholder="怎么称呼你"
                autoComplete="nickname"
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </label>
          )}
          <label>
            邮箱
            <input
              type="email"
              value={email}
              placeholder="you@school.edu.cn"
              autoComplete="email"
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label>
            密码
            <input
              type="password"
              value={password}
              placeholder="至少 8 位"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          {error && <p className="form-error">{error}</p>}

          <button className="primary-button login-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting
              ? <LoaderCircle className="spin" size={16} />
              : <Sparkles size={16} />}
            {mode === 'login' ? '登录' : '注册并开始'}
          </button>
        </form>

        <button
          className="login-switch"
          type="button"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            setError('')
          }}
        >
          {mode === 'login' ? '没有账号？注册一个 →' : '已有账号？直接登录 →'}
        </button>
      </div>
    </div>
  )
}
