export function getApiKey(): string {
  return localStorage.getItem("gemini_api_key") || "";
}

export function setApiKey(key: string): void {
  localStorage.setItem("gemini_api_key", key);
}

export function hasApiKey(): boolean {
  return !!getApiKey();
}
