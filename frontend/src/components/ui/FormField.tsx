interface FieldErrorProps {
  message?: string
}

export function FieldError({ message }: FieldErrorProps) {
  if (!message) return null
  return (
    <p className="mt-1 text-xs text-ledger-red font-sans animate-fade-in">
      {message}
    </p>
  )
}

interface FormFieldProps {
  label:     string
  error?:    string
  children:  React.ReactNode
  hint?:     string
  required?: boolean
}

export function FormField({ label, error, children, hint, required }: FormFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-text-2 tracking-wide uppercase">
        {label}
        {required && <span className="text-ledger-red ml-1">*</span>}
      </label>
      {children}
      {hint && !error && <p className="text-xs text-text-3">{hint}</p>}
      <FieldError message={error} />
    </div>
  )
}
