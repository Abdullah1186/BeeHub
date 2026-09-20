import { useState } from "react";
import { supabase } from "../lib/supabase";
import { Button, Card, Input, Wordmark } from "../ui";

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
      <div className="w-full max-w-sm fade-up">
        <Wordmark size={36} />
        <p className="mt-3 text-sm text-[var(--text-muted)]">
          Practice Arabic from your own books.
        </p>

        {sent ? (
          <Card className="mt-8 bg-[var(--accent-soft)] p-5">
            <p className="text-sm text-[var(--accent-text)]">
              Check <span className="font-medium">{email}</span> for a sign-in link.
            </p>
            <Button
              variant="ghost"
              size="sm"
              className="mt-3"
              onClick={() => {
                setSent(false);
                setMode("password");
              }}
            >
              Use a password instead
            </Button>
          </Card>
        ) : (
          <form onSubmit={signIn} className="mt-8 space-y-3">
            <Input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />

            {mode === "password" && (
              <Input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
              />
            )}

            <Button type="submit" size="lg" loading={busy} className="w-full">
              {busy ? "Working…" : mode === "password" ? "Sign in" : "Send sign-in link"}
            </Button>

            {error && <p className="text-sm text-[var(--bad-text)]">{error}</p>}

            <Button
              type="button"
              variant="ghost"
              className="w-full"
              onClick={() => {
                setMode(mode === "password" ? "link" : "password");
                setError(null);
              }}
            >
              {mode === "password" ? "Email me a link instead" : "Use a password instead"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
