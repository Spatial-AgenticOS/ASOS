"use client";

import { useState } from "react";

const TABS = [
  {
    label: "One-liner",
    code: `curl -sSL https://raw.githubusercontent.com/FERAL-AI/FERAL-AI/main/scripts/install.sh | bash`,
    note: "Creates ~/.feral-env, installs everything, runs setup wizard.",
  },
  {
    label: "Clone",
    code: `git clone https://github.com/FERAL-AI/FERAL-AI.git && cd FERAL-AI
make install
feral start`,
    note: "Full repo. Requires Python 3.11+ and Node 20+.",
  },
  {
    label: "Docker",
    code: `git clone https://github.com/FERAL-AI/FERAL-AI.git && cd FERAL-AI
docker compose up`,
    note: "Brain + client + registry. Open localhost:9090.",
  },
];

export default function InstallTabs() {
  const [active, setActive] = useState(0);
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(TABS[active].code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section className="border-t border-border px-6 py-20 sm:py-28">
      <div className="mx-auto max-w-3xl">
        <h2 className="text-center text-3xl sm:text-4xl font-black tracking-tight">
          Get started in 60 seconds
        </h2>

        <div className="mt-10 flex justify-center gap-2">
          {TABS.map((t, i) => (
            <button
              key={t.label}
              onClick={() => setActive(i)}
              className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
                i === active
                  ? "bg-foreground text-background"
                  : "bg-card text-muted hover:text-foreground"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="mt-6 rounded-2xl border border-border bg-card p-6">
          <div className="flex items-start justify-between">
            <pre className="overflow-x-auto font-mono text-sm leading-relaxed">
              {TABS[active].code}
            </pre>
            <button
              onClick={copy}
              className="copy-btn ml-4 shrink-0 rounded-lg bg-foreground/10 px-3 py-1.5 text-xs font-medium transition hover:bg-foreground/20"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
          <p className="mt-4 text-xs text-muted">{TABS[active].note}</p>
        </div>
      </div>
    </section>
  );
}
