import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "./lib/supabase";
import { Auth } from "./components/Auth";
import { Practice } from "./components/Practice";
import { Resources } from "./components/Resources";

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [practising, setPractising] = useState<string | null>(null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (!ready) return null;
  if (!session) return <Auth />;

  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <button
            onClick={() => setPractising(null)}
            className="text-lg font-semibold text-bee-700"
          >
            BeeHub
          </button>
          <button
            onClick={() => supabase.auth.signOut()}
            className="text-sm text-stone-500 hover:text-stone-800"
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-8">
        {practising ? (
          <Practice resourceId={practising} onBack={() => setPractising(null)} />
        ) : (
          <Resources onPractice={setPractising} />
        )}
      </main>
    </div>
  );
}
