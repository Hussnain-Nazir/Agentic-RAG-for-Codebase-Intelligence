import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";
import { useState } from "react";

import { authToken } from "../../api/client";
import { useLogin, useRegister } from "../../api/hooks";
import { ErrorNotice } from "../../components/common/Shell";

const loginSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});
const registerSchema = loginSchema.extend({ password: z.string().min(8, "Use at least 8 characters").max(128) });
type Credentials = z.infer<typeof loginSchema>;

function AuthForm({ mode }: { mode: "login" | "register" }) {
  const [passwordVisible, setPasswordVisible] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const login = useLogin();
  const register = useRegister();
  const schema = mode === "login" ? loginSchema : registerSchema;
  const { register: field, handleSubmit, formState: { errors } } = useForm<Credentials>({ resolver: zodResolver(schema) });
  const pending = login.isPending || register.isPending;
  const error = register.error || login.error;

  const submit = handleSubmit(async ({ email, password }) => {
    try {
      if (mode === "register") await register.mutateAsync({ email, password });
      const result = await login.mutateAsync({ email, password });
      queryClient.clear();
      authToken.set(result.access_token);
      navigate("/dashboard", { replace: true });
    } catch { /* Mutation state displays the server error. */ }
  });

  return <div className="flex min-h-screen items-center justify-center bg-slate-950 px-6 py-12 text-slate-100">
    <main className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-8 shadow-xl">
      <Link to="/" className="text-sm font-semibold uppercase tracking-widest text-cyan-400">Prism</Link>
      <h1 className="mt-5 text-3xl font-semibold">{mode === "login" ? "Sign in" : "Create account"}</h1>
      <p className="mt-2 text-sm text-slate-400">Repository intelligence workspace</p>
      <form onSubmit={submit} className="mt-8 space-y-5" noValidate>
        <div>
          <label htmlFor="email" className="block text-sm font-medium">Email</label>
          <input id="email" type="email" autoComplete="email" {...field("email")} className="input mt-2" aria-invalid={!!errors.email} />
          {errors.email && <p role="alert" className="mt-1 text-sm text-rose-300">{errors.email.message}</p>}
        </div>
        <div>
          <label htmlFor="password" className="block text-sm font-medium">Password</label>
          <div className="relative mt-2">
            <input id="password" type={passwordVisible ? "text" : "password"} autoComplete={mode === "login" ? "current-password" : "new-password"} {...field("password")} className="input pr-12" aria-invalid={!!errors.password} />
            <button type="button" className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-slate-400 hover:text-white" aria-label={passwordVisible ? "Hide password" : "Show password"} aria-pressed={passwordVisible} onClick={() => setPasswordVisible((visible) => !visible)}>
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
                {passwordVisible ? <><path d="M3 3l18 18" /><path d="M10.6 5.2A10.8 10.8 0 0 1 12 5c5.1 0 9 4.7 10 7-0.5 1.2-2.1 3.4-4.4 5" /><path d="M6.3 6.3C4.1 7.8 2.6 10 2 12c1 2.3 4.9 7 10 7 1.3 0 2.5-.3 3.6-.8" /></> : <><path d="M2 12s3.8-7 10-7 10 7 10 7-3.8 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>}
              </svg>
            </button>
          </div>
          {errors.password && <p role="alert" className="mt-1 text-sm text-rose-300">{errors.password.message}</p>}
        </div>
        {error && <ErrorNotice message={error.message} />}
        <button className="button-primary w-full" type="submit" disabled={pending}>{pending ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}</button>
      </form>
      <p className="mt-6 text-center text-sm text-slate-400">
        {mode === "login" ? "New to Prism?" : "Already have an account?"} {" "}
        <Link className="text-cyan-400 underline" to={mode === "login" ? "/register" : "/login"}>
          {mode === "login" ? "Create account" : "Sign in"}
        </Link>
      </p>
    </main>
  </div>;
}

export function LoginPage() { return <AuthForm mode="login" />; }
export function RegisterPage() { return <AuthForm mode="register" />; }
