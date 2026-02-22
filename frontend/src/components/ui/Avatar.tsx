interface AvatarProps {
  name:      string
  size?:     'xs' | 'sm' | 'md' | 'lg'
  className?: string
}

const PALETTE = [
  'bg-ledger-green/20 text-ledger-green',
  'bg-ledger-blue/20 text-ledger-blue',
  'bg-ledger-purple/20 text-ledger-purple',
  'bg-ledger-yellow/20 text-ledger-yellow',
  'bg-ledger-red/20 text-ledger-red',
]

function hashName(name: string): number {
  return name.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0)
}

export function Avatar({ name, size = 'md', className = '' }: AvatarProps) {
  const initials  = name.slice(0, 2).toUpperCase()
  const colorClass = PALETTE[hashName(name) % PALETTE.length]
  const sizeClass  = {
    xs: 'h-6 w-6 text-xs',
    sm: 'h-8 w-8 text-xs',
    md: 'h-9 w-9 text-sm',
    lg: 'h-12 w-12 text-base',
  }[size]

  return (
    <div
      className={`${sizeClass} ${colorClass} ${className}
        rounded-full flex items-center justify-center
        font-mono font-medium shrink-0 select-none`}
    >
      {initials}
    </div>
  )
}
