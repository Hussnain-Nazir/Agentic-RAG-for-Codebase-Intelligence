const PREFIX = "prism_conversation_v1:";
const MAX_STORED_CHARS = 1_000_000;
const USER_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function conversationKey(token: string | null, repositoryId: string): string | null {
  if (!token || !repositoryId) return null;
  try {
    const payload = token.split(".")[1];
    const encoded = payload.replace(/-/g, "+").replace(/_/g, "/");
    const parsed = JSON.parse(atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, "="))) as { sub?: unknown };
    if (typeof parsed.sub !== "string" || !USER_ID_PATTERN.test(parsed.sub)) return null;
    return `${PREFIX}${parsed.sub.toLowerCase()}:${encodeURIComponent(repositoryId)}`;
  } catch {
    return null;
  }
}

export function readConversation<T>(key: string | null): T[] {
  if (!key) return [];
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw || raw.length > MAX_STORED_CHARS) return [];
    const turns = JSON.parse(raw) as unknown;
    return Array.isArray(turns) ? turns as T[] : [];
  } catch {
    return [];
  }
}

export function writeConversation<T>(key: string | null, turns: T[]): boolean {
  if (!key) return true;
  try {
    if (turns.length === 0) {
      sessionStorage.removeItem(key);
      return true;
    }
    const raw = JSON.stringify(turns);
    if (raw.length > MAX_STORED_CHARS) {
      sessionStorage.removeItem(key);
      return false;
    }
    sessionStorage.setItem(key, raw);
    return true;
  } catch {
    try { sessionStorage.removeItem(key); } catch { /* Storage may be disabled. */ }
    return false;
  }
}

export function clearConversation(key: string | null): void {
  if (!key) return;
  try { sessionStorage.removeItem(key); } catch { /* Storage may be disabled. */ }
}

export function clearAllConversations(): void {
  try {
    const keys = Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index))
      .filter((key): key is string => !!key && key.startsWith(PREFIX));
    keys.forEach((key) => sessionStorage.removeItem(key));
  } catch { /* Sign-out must still work if storage is unavailable. */ }
}
