import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useAuth } from '@/auth/AuthContext'
import { loginSchema, type LoginForm } from '@/schemas'
import { FormField } from '@/components/ui/FormField'
import { Spinner } from '@/components/ui/Spinner'
import { extractApiError } from '@/api/client'

export function LoginPage() {
  const { login }      = useAuth()
  const navigate       = useNavigate()
  const [apiErr, setApiErr] = useState('')

  const {
    register, handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema) })

  const onSubmit = async (data: LoginForm) => {
    setApiErr('')
    try {
      await login(data)
      navigate('/dashboard')
    } catch (err) {
      setApiErr(extractApiError(err).message)
    }
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center px-4">
      {/* Background texture */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[600px] h-[400px]
                        bg-ledger-green/3 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-[400px] h-[300px]
                        bg-ledger-blue/3 rounded-full blur-3xl" />
      </div>

      <div className="w-full max-w-sm relative animate-slide-up">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12
                          rounded-xl bg-ledger-green/10 border border-ledger-green/30 mb-4">
            <span className="text-ledger-green font-mono font-bold text-xl">₹</span>
          </div>
          <h1 className="font-display text-3xl text-text">SplitLedger</h1>
          <p className="text-sm text-text-3 mt-1">Every split, perfectly balanced.</p>
        </div>

        {/* Card */}
        <div className="card p-6 space-y-4">
          <h2 className="font-display text-xl text-text">Sign in</h2>

          {apiErr && (
            <div className="bg-ledger-red/10 border border-ledger-red/30 rounded-lg px-3 py-2.5
                            text-sm text-ledger-red animate-fade-in">
              {apiErr}
            </div>
          )}

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <FormField label="Username" error={errors.username?.message}>
              <input
                {...register('username')}
                className={`input ${errors.username ? 'input-error' : ''}`}
                placeholder="your_username"
                autoComplete="username"
              />
            </FormField>

            <FormField label="Password" error={errors.password?.message}>
              <input
                {...register('password')}
                type="password"
                className={`input ${errors.password ? 'input-error' : ''}`}
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </FormField>

            <button
              type="submit"
              disabled={isSubmitting}
              className="btn-md btn-primary w-full mt-2"
            >
              {isSubmitting ? <Spinner size="sm" /> : 'Sign In'}
            </button>
          </form>
        </div>

        <p className="text-center text-sm text-text-3 mt-4">
          No account?{' '}
          <Link to="/register" className="text-ledger-green hover:text-green-300 transition-colors">
            Create one
          </Link>
        </p>
      </div>
    </div>
  )
}
