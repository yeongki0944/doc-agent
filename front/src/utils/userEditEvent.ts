/**
 * Simple event bus for user field edits.
 * When a user directly edits a field, this notifies the chat panel
 * so the LLM can maintain context about user changes.
 */

type EditListener = (section: string, field: string, oldValue: string, newValue: string) => void

const listeners = new Set<EditListener>()

export function onUserEdit(listener: EditListener) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function emitUserEdit(section: string, field: string, oldValue: string, newValue: string) {
  listeners.forEach(fn => fn(section, field, oldValue, newValue))
}
