import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";
import { useState } from "react";
import { GitBranch, ScanSearch, ShieldCheck } from "lucide-react";

import { authToken } from "../../api/client";
import { useLogin, useRegister } from "../../api/hooks";
import { ErrorNotice } from "../../components/common/Shell";
import { PrismLogo } from "../../components/common/PrismLogo";

const loginSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});
const registerSchema = loginSchema.extend({ password: z.string().min(8, "Use at least 8 characters").max(128) });
type Credentials = z.infer<typeof loginSchema>;

const highlights = [
  { icon: ScanSearch, text: "Ask grounded questions about any indexed repository." },
  { icon: GitBranch, text: "Trace multi-file flows and change impact with cited evidence." },
  { icon: ShieldCheck, text: "Read-only GitHub App access. Prism never modifies your code." },
];

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

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-canvas px-6 py-12 text-ink-primary">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.05]"
        style={{
          backgroundImage: "linear-gradient(#e6edf3 1px, transparent 1px), linear-gradient(90deg, #e6edf3 1px, transparent 1px)",
          backgroundSize: "42px 42px",
        }}
      />
      <div aria-hidden className="pointer-events-none absolute left-1/2 top-0 h-[420px] w-[620px] -translate-x-1/2 rounded-full bg-accent/10 blur-[120px]" />

      <div className="relative grid w-full max-w-4xl gap-10 lg:grid-cols-[1.05fr_1fr] lg:items-center">
        <div className="hidden lg:block">
          <PrismLogo size={40} />
          <h2 className="mt-6 max-w-sm text-3xl font-semibold leading-tight tracking-tight text-ink-primary">
            Repository intelligence, grounded in evidence.
          </h2>
          <ul className="mt-8 space-y-4">
            {highlights.map((item) => (
              <li key={item.text} className="flex items-start gap-3 text-sm text-ink-secondary">
                <item.icon size={17} strokeWidth={1.75} className="mt-0.5 shrink-0 text-accent-hover" />
                <span>{item.text}</span>
              </li>
            ))}
          </ul>
        </div>

        <main className="w-full animate-slide-up rounded-xl border border-border bg-surface-2 p-8 shadow-overlay">
          <Link to="/" className="flex items-center gap-2 lg:hidden">
            <PrismLogo size={22} />
            <span className="text-sm font-semibold uppercase tracking-widest text-ink-secondary">Prism</span>
          </Link>
          <h1 className="mt-5 text-2xl font-semibold tracking-tight text-ink-primary lg:mt-0">
            {mode === "login" ? "Sign in" : "Create account"}
          </h1>
          <p className="mt-2 text-sm text-ink-secondary">Repository intelligence workspace</p>
          <form onSubmit={submit} className="mt-7 space-y-5" noValidate>
            <div>
              <label htmlFor="email" className="label">Email</label>
              <input id="email" type="email" autoComplete="email" {...field("email")} className="input" aria-invalid={!!errors.email} />
              {errors.email && <p role="alert" className="mt-1.5 text-sm text-danger">{errors.email.message}</p>}
            </div>
            <div>
              <label htmlFor="password" className="label">Password</label>
              <div className="relative">
                <input id="password" type={passwordVisible ? "text" : "password"} autoComplete={mode === "login" ? "current-password" : "new-password"} {...field("password")} className="input pr-12" aria-invalid={!!errors.password} />
                <button type="button" className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-ink-secondary hover:text-ink-primary" aria-label={passwordVisible ? "Hide password" : "Show password"} aria-pressed={passwordVisible} onClick={() => setPasswordVisible((visible) => !visible)}>
                  <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
                    {passwordVisible ? <><path d="M3 3l18 18" /><path d="M10.6 5.2A10.8 10.8 0 0 1 12 5c5.1 0 9 4.7 10 7-0.5 1.2-2.1 3.4-4.4 5" /><path d="M6.3 6.3C4.1 7.8 2.6 10 2 12c1 2.3 4.9 7 10 7 1.3 0 2.5-.3 3.6-.8" /></> : <><path d="M2 12s3.8-7 10-7 10 7 10 7-3.8 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>}
                  </svg>
                </button>
              </div>
              {errors.password && <p role="alert" className="mt-1.5 text-sm text-danger">{errors.password.message}</p>}
            </div>
            {error && <ErrorNotice message={error.message} />}
            <button className="button-primary w-full" type="submit" disabled={pending}>
              {pending ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>
          <p className="mt-6 text-center text-sm text-ink-secondary">
            {mode === "login" ? "New to Prism?" : "Already have an account?"}{" "}
            <Link className="font-medium text-accent-hover underline underline-offset-2" to={mode === "login" ? "/register" : "/login"}>
              {mode === "login" ? "Create account" : "Sign in"}
            </Link>
          </p>
        </main>
      </div>
    </div>
  );
}

export function LoginPage() { return <AuthForm mode="login" />; }
export function RegisterPage() { return <AuthForm mode="register" />; }
