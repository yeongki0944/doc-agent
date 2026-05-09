import { useEffect, useState } from 'react'

/**
 * Minimal hash-based router for the app. We prefer this over a real router
 * library because the app only has a handful of top-level screens and
 * adding react-router / hash-history would pull in unnecessary weight.
 *
 * Usage:
 *   const route = useHashRoute()
 *   if (route === '#/admin/rules') return <ReviewRulesAdmin />
 *
 *   navigate('#/admin/rules')  // changes hash + triggers listeners
 */

export function useHashRoute(): string {
  const [hash, setHash] = useState<string>(() => window.location.hash || '#/')
  useEffect(() => {
    const onChange = () => setHash(window.location.hash || '#/')
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash
}

export function navigate(target: string) {
  if (window.location.hash === target) return
  window.location.hash = target
}
