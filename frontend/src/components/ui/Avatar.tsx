import clsx from 'clsx'

interface AvatarProps {
  name: string
  size?: 'xs' | 'sm' | 'md' | 'lg'
}

export function Avatar({ name, size = 'md' }: AvatarProps) {
  // 1. SAFELY HANDLE MISSING NAMES IMMEDIATELY
  const safeName = name || '?'

  // 2. Hash function now uses safeName
  const hashName = (str: string) => {
    let hash = 0
    // Use safeName here in case the direct string passed is somehow undefined
    const safeStr = str || '?'
    for (let i = 0; i < safeStr.length; i++) {
      hash = safeStr.charCodeAt(i) + ((hash << 5) - hash)
    }
    return hash
  }

  // 3. Initials now uses safeName
  const initials = safeName.slice(0, 2).toUpperCase()

  // 4. Color generation
  const colors = [
    'bg-ledger-blue',
    'bg-ledger-green',
    'bg-ledger-purple',
    'bg-ledger-yellow',
    'bg-ledger-red',
  ]
  const colorClass = colors[Math.abs(hashName(safeName)) % colors.length]

  const sizeClasses = {
    xs: 'w-5 h-5 text-[10px]',
    sm: 'w-6 h-6 text-xs',
    md: 'w-8 h-8 text-sm',
    lg: 'w-10 h-10 text-base',
  }

  return (
      <div
          className={clsx(
              'rounded-full flex items-center justify-center font-medium text-bg shrink-0',
              colorClass,
              sizeClasses[size]
          )}
          title={safeName} // Tooltip will show the name or '?'
      >
        {initials}
      </div>
  )
}