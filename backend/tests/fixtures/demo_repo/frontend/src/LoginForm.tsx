import { useState } from "react";
import type { FormEvent } from "react";
import { login } from "./api";

export function LoginForm({ onLogin }: { onLogin: (token: string) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const result = await login({ email, password });
      onLogin(result.access_token);
    } catch {
      setError("Login failed");
    }
  }

  return <form onSubmit={submit}>
    <label>Email <input value={email} onChange={(event) => setEmail(event.target.value)} /></label>
    <label>Password <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
    <button type="submit">Sign in</button>
    {error && <p role="alert">{error}</p>}
  </form>;
}
