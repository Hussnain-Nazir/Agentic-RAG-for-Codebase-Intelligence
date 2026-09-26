import { useState } from "react";
import type { FormEvent } from "react";
import { register } from "./api";

export function RegisterForm({ onRegistered }: { onRegistered: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await register({ email, password });
      onRegistered();
    } catch { setError("Registration failed"); }
  }

  return <form onSubmit={submit}>
    <label>Email <input value={email} onChange={(event) => setEmail(event.target.value)} /></label>
    <label>Password <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
    <button type="submit">Create account</button>
    {error && <p role="alert">{error}</p>}
  </form>;
}
