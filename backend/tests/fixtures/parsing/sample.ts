export interface User {
  id: number;
}

export type UserId = string;

export function loadUser(): User {
  return fetch("/api/users/1") as unknown as User;
}
