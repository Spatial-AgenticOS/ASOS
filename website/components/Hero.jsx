"use client";

import { useState } from "react";

const INSTALL_CMD =
  "curl -sSL https://raw.githubusercontent.com/FERAL-AI/FERAL-AI/main/scripts/install.sh | bash";

export default function Hero() {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(INSTALL_CMD);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section className="relative overflow-hidden px-6 pt-20 pb-24 sm:pt-32 sm:pb-32">
      <div className="mx-auto max-w-4xl text-center">
        <img
          src="/feral-banner.png"
          alt="FERAL"
          className="mx-auto mb-8 h-28 sm:h-36 rounded-2xl"
        />

        <h1 className="text-5xl sm:text-7xl font-black tracking-tight">
          FERAL
        </h1>
        <p className="mt-2 text-xl sm:text-2xl font-semibold text-accent">
          Unleashed AI
        </p>

        <p className="mx-auto mt-6 max-w-2xl text-lg text-muted leading-relaxed">
          The open-source AI brain that lives on{" "}
          <span className="text-foreground font-semibold">your devices</span>,
          not someone else&apos;s cloud. It knows your heartbeat. It sees your
          screen. It controls your home. It remembers everything. And it{" "}
          <span className="text-danger font-semibold">never phones home</span>.
        </p>

        <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
          <button
            onClick={copy}
            className="copy-btn group relative flex items-center gap-3 rounded-xl bg-foreground px-6 py-3.5 font-mono text-sm text-background transition hover:opacity-90"
          >
            <span className="truncate max-w-xs sm:max-w-md">
              $ curl -sSL ... | bash
            </span>
            <span className="shrink-0 text-xs opacity-60 group-hover:opacity-100">
              {copied ? "Copied!" : "Copy"}
            </span>
          </button>

          <a
            href="https://github.com/FERAL-AI/FERAL-AI"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-xl border border-border px-6 py-3.5 text-sm font-medium transition hover:bg-card"
          >
            <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12Z" />
            </svg>
            GitHub
          </a>
        </div>

        <div className="mt-6 flex items-center justify-center gap-3 text-xs text-muted">
          <img
            src="https://img.shields.io/github/stars/FERAL-AI/FERAL-AI?style=flat-square&color=06b6d4"
            alt="Stars"
            className="h-5"
          />
          <img
            src="https://img.shields.io/github/last-commit/FERAL-AI/FERAL-AI?style=flat-square&color=06b6d4"
            alt="Last Commit"
            className="h-5"
          />
          <span>Apache 2.0</span>
        </div>
      </div>
    </section>
  );
}
