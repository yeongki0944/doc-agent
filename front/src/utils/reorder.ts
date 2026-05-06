import type { StructuredBullet } from '../store/documentStore'

export function moveItem<T>(items: T[], fromIndex: number, toIndex: number): T[] {
  if (
    fromIndex === toIndex ||
    fromIndex < 0 ||
    toIndex < 0 ||
    fromIndex >= items.length ||
    toIndex >= items.length
  ) {
    return items
  }

  const next = [...items]
  const [moved] = next.splice(fromIndex, 1)
  next.splice(toIndex, 0, moved)
  return next
}

export function normalizeStructuredBulletLevels(items: StructuredBullet[]): StructuredBullet[] {
  let hasLevelOneAbove = false

  return items.map((item, index) => {
    if (item.level === 1) {
      hasLevelOneAbove = true
      return item
    }

    if (index === 0 || !hasLevelOneAbove) {
      hasLevelOneAbove = true
      return { ...item, level: 1 }
    }

    return item
  })
}
