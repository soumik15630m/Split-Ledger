import { moneySign, formatMoney, type MoneyString } from '@/types'
import clsx from 'clsx'

interface MoneyDisplayProps {
  amount:     MoneyString
  showSign?:  boolean
  size?:      'xs' | 'sm' | 'md' | 'lg' | 'xl'
  className?: string
  neutral?:   boolean   // forces neutral/white colour (e.g. for expense amount)
}

export function MoneyDisplay({
  amount,
  showSign,
  size = 'md',
  className = '',
  neutral = false,
}: MoneyDisplayProps) {
  const sign = moneySign(amount)

  const colorClass = neutral
    ? 'text-text'
    : {
        positive: 'money-positive',
        negative: 'money-negative',
        zero:     'money-zero',
      }[sign]

  const sizeClass = {
    xs: 'text-xs',
    sm: 'text-sm',
    md: 'text-base',
    lg: 'text-xl',
    xl: 'text-3xl',
  }[size]

  return (
    <span className={clsx('money', colorClass, sizeClass, className)}>
      {formatMoney(amount, { showSign: showSign && sign !== 'zero' })}
    </span>
  )
}
