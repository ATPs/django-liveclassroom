let slot: HTMLElement | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  listeners.forEach((listener) => listener());
}

export function setSessionActionSlot(next: HTMLElement | null): void {
  if (slot === next) return;
  slot = next;
  notify();
}

export function clearSessionActionSlot(expected: HTMLElement | null): void {
  if (slot !== expected) return;
  setSessionActionSlot(null);
}

export function getSessionActionSlot(): HTMLElement | null {
  return slot ?? document.getElementById("lc-session-action-slot");
}

export function subscribeSessionActionSlot(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
