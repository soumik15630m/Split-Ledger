import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useAuth } from '@/auth/AuthContext'
import { registerSchema, type RegisterForm } from '@/schemas'
import { FormField } from '@/components/ui/FormField'
import { Spinner } from '@/components/ui/Spinner'
import { extractApiError } from '@/api/client'

export function RegisterPage() {
  const { register: authRegister } = useAuth()
  const navigate                   = useNavigate()
  const [apiErr, setApiErr]        = useState('')

  const {
    register, handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterForm>({ resolver: zodResolver(registerSchema) })

  const onSubmit = async (data: RegisterForm) => {
    setApiErr('')
    try {
      await authRegister(data)
      navigate('/dashboard')
    } catch (err) {
      setApiErr(extractApiError(err).message)
    }
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center px-4">
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-1/3 right-1/3 w-[500px] h-[350px]
                        bg-ledger-purple/3 rounded-full blur-3xl" />
      </div>

      <div className="w-full max-w-sm relative animate-slide-up">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12
                          rounded-xl bg-ledger-green/10 border border-ledger-green/30 mb-4">
            <span className="text-ledger-green font-mono font-bold text-xl">₹</span>
          </div>
          <h1 className="font-display text-3xl text-text">SplitLedger</h1>
          <p className="text-sm text-text-3 mt-1">Create your account</p>
        </div>

        <div className="card p-6 space-y-4">
          <h2 className="font-display text-xl text-text">Get started</h2>

          {apiErr && (
            <div className="bg-ledger-red/10 border border-ledger-red/30 rounded-lg px-3 py-2.5
                            text-sm text-ledger-red animate-fade-in">
              {apiErr}
            </div>
          )}

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <FormField label="Username" error={errors.username?.message}
              hint="3–50 chars, letters / numbers / underscores">
              <input
                {...register('username')}
                className={`input ${errors.username ? 'input-error' : ''}`}
                placeholder="alice_99"
                autoComplete="username"
              />
            </FormField>

            <FormField label="Email" error={errors.email?.message}>
              <input
                {...register('email')}
                type="email"
                className={`input ${errors.email ? 'input-error' : ''}`}
                placeholder="alice@example.com"
                autoComplete="email"
              />
            </FormField>

            <FormField label="Password" error={errors.password?.message}
              hint="At least 8 chars, 1 letter, 1 number">
              <input
                {...register('password')}
                type="password"
                className={`input ${errors.password ? 'input-error' : ''}`}
                placeholder="••••••••"
                autoComplete="new-password"
              />
            </FormField>

            <button
              type="submit"
              disabled={isSubmitting}
              className="btn-md btn-primary w-full mt-2"
            >
              {isSubmitting ? <Spinner size="sm" /> : 'Create Account'}
            </button>
          </form>
        </div>

        <p className="text-center text-sm text-text-3 mt-4">
          Already have an account?{' '}
          <Link to="/login" className="text-ledger-green hover:text-green-300 transition-colors">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
