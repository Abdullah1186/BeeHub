import { useState } from "react";
import { supabase } from "../lib/supabase";

/**
 * Two sign-in paths.
 *
 * Magic link is the spec's choice (§3) and the default. Password exists because
 * Supabase's built-in SMTP allows only a few emails per hour, which makes
 * link-only sign-in unusable during development. Once real SMTP is configured,
 * the password path can stay or go.
 */
export function Auth() {
  const [mode, setMode] = useState<"password" | "link">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);

    if (mode === "password") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      setBusy(false);
      if (error) setError(error.message);
      // On success the session listener in App swaps the screen.
      return;
    }

    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: window.location.origin },
    });
    setBusy(false);
    if (error) {
      setError(
        error.message.includes("rate limit")
          ? "Email rate limit reached. Use a password instead, or wait ~30 minutes."
          : error.message,
      );
    } else {
      setSent(true);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-3xl font-semibold text-bee-700">BeeHub</h1>
        <p className="mt-1 text-sm text-stone-500">
          Practice Arabic from your own books.
        </p>

        {sent ? (
          <div className="mt-8 rounded-lg bg-bee-50 border border-bee-100 p-4">
            <p className="text-sm text-stone-700">
              Check <span className="font-medium">{email}</span> for a sign-in link.
            </p>
            <button
              onClick={() => {
                setSent(false);
                setMode("password");
              }}
              className="mt-3 text-sm text-bee-700 underline"
            >
              Use a password instead
            </button>
          </div>
        ) : (
          <form onSubmit={signIn} className="mt-8 space-y-3">
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm
                         focus:border-bee-500 focus:outline-none focus:ring-1 focus:ring-bee-500"
            />

            {mode === "password" && (
              <input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
                className="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm
                           focus:border-bee-500 focus:outline-none focus:ring-1 focus:ring-bee-500"
              />
            )}

            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-lg bg-bee-600 px-3 py-2 text-sm font-medium text-white
                         hover:bg-bee-700 disabled:opacity-50"
            >
              {busy
                ? "Working…"
                : mode === "password"
                  ? "Sign in"
                  : "Send sign-in link"}
            </button>

            {error && <p className="text-sm text-red-600">{error}</p>}

            <button
              type="button"
              onClick={() => {
                setMode(mode === "password" ? "link" : "password");
                setError(null);
              }}
              className="w-full text-center text-sm text-stone-500 hover:text-stone-800"
            >
              {mode === "password" ? "Email me a link instead" : "Use a password instead"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
