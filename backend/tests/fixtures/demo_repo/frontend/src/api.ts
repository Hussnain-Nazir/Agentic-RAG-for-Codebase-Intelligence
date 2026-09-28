import type { Credentials, Item } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

async function request<T>(path: string, token: string | null, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function login(credentials: Credentials): Promise<{ access_token: string }> {
  return request("/auth/login", null, { method: "POST", body: JSON.stringify(credentials) });
}

export function register(credentials: Credentials): Promise<{ user_id: number }> {
  return request("/auth/register", null, {
    method: "POST", body: JSON.stringify({ ...credentials, organization_id: 1 }),
  });
}

export function listItems(token: string): Promise<Item[]> {
  return request("/items", token);
}

export function createItem(token: string, title: string): Promise<Item> {
  return request("/items", token, { method: "POST", body: JSON.stringify({ title }) });
}

export function updateItem(token: string, id: number, title: string): Promise<Item> {
  return request(`/items/${id}`, token, { method: "PUT", body: JSON.stringify({ title }) });
}

export function deleteItem(token: string, id: number): Promise<void> {
  return request(`/items/${id}`, token, { method: "DELETE" });
}
