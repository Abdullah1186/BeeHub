import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "./lib/supabase";
import { Auth } from "./components/Auth";
import { Home } from "./components/Home";
import { Learning } from "./components/Learning";
import { Metrics } from "./components/Metrics";
import { Resources } from "./components/Resources";
import { Button, Wordmark } from "./ui";

/** The spec's §2 tabs. Settings is Phase 4; Review lives inside Learning
 *  until the spaced-repetition queue exists. */
const TABS = [
  { id: "home", label: "Home" },
  { id: "resources", label: "Resources" },
  { id: "learning", label: "Learning" },
  { id: "metrics", label: "Metrics" },
] as const;

export type Tab = (typeof TABS)[number]["id"];

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState<Tab>("home");
  // Set when Home or Resources sends you into Learning for a specific book.
  const [focusResource, setFocusResource] = useState<string | null>(null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  function goLearn(resourceId: string | null) {
    setFocusResource(resourceId);
    setTab("learning");
  }

  if (!ready) return null;
  if (!session) return <Auth />;

  return (
    <div className="min-h-screen">
      <header className="sticky z-20 border-b border-[var(--border)]
                         bg-[var(--surface)]/85 backdrop-blur-md"
              style={{ top: "env(safe-area-inset-top, 0px)" }}>
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-4 py-3">
          <button onClick={() => setTab("home")} aria-label="Home">
            <Wordmark size={30} />
          </button>

          <nav className="hidden gap-1 sm:flex">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                aria-current={tab === t.id ? "page" : undefined}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                  tab === t.id
                    ? "bg-[var(--accent-soft)] text-[var(--accent-text)]"
                    : "text-[var(--text-muted)] hover:bg-[var(--surface-alt)] hover:text-[var(--text)]"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>

          <Button variant="ghost" size="sm" onClick={() => supabase.auth.signOut()}>
            Sign out
          </Button>
        </div>

        {/* Narrow screens get the tabs on their own row rather than a menu. */}
        <nav className="flex gap-1 overflow-x-auto px-4 pb-2 sm:hidden">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium ${
                tab === t.id
                  ? "bg-[var(--accent-soft)] text-[var(--accent-text)]"
                  : "text-[var(--text-muted)]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-8">
        {tab === "home" && <Home onLearn={goLearn} onBrowse={() => setTab("resources")} />}
        {tab === "resources" && <Resources onPractice={goLearn} />}
        {tab === "learning" && (
          <Learning focusResource={focusResource} onBrowse={() => setTab("resources")} />
        )}
        {tab === "metrics" && <Metrics />}
      </main>
    </div>
  );
}
