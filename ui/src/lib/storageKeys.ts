/**
 * Carry a localStorage entry over from a pre-rename key (Dograh / Failte AI) to
 * its Fallcha.ai key so returning visitors keep their state. Copies the old
 * value only when the new key is still empty, then removes the old key. Safe to
 * call repeatedly and on every read; storage being unavailable (SSR, private
 * mode, blocked site data) is a silent no-op.
 */
export function migrateStorageKey(oldKey: string, newKey: string): void {
  if (oldKey === newKey) return;
  try {
    const storage = globalThis.localStorage;
    if (!storage) return;
    const legacyValue = storage.getItem(oldKey);
    if (legacyValue === null) return;
    if (storage.getItem(newKey) === null) {
      storage.setItem(newKey, legacyValue);
    }
    storage.removeItem(oldKey);
  } catch {
    // Storage unavailable or full; the caller simply starts fresh.
  }
}
