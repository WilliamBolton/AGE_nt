export function getApiKey(): string {
  return localStorage.getItem("gemini_api_key") || "";
}

export function setApiKey(key: string): void {
  localStorage.setItem("gemini_api_key", key);
}

export function hasApiKey(): boolean {
  // Always return true — server falls back to .env GEMINI_API_KEY
  // If neither is set, the server returns 401 which the chat catches gracefully
  return true;
}
