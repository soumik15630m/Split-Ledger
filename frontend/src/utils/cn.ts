import clsx, { type ClassValue } from 'clsx'

/** Merge class names conditionally. Thin wrapper around clsx. */
export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs)
}
