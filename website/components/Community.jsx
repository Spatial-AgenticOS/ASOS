export default function Community() {
  return (
    <section className="border-t border-border px-6 py-20 sm:py-28">
      <div className="mx-auto max-w-3xl text-center">
        <h2 className="text-3xl sm:text-4xl font-black tracking-tight">
          Join the pack
        </h2>
        <p className="mt-4 text-muted">
          FERAL is open source. Contribute skills, hardware adapters, GenUI
          providers, or just break things and file issues.
        </p>

        <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
          <a
            href="https://github.com/FERAL-AI/FERAL-AI"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-xl bg-foreground px-6 py-3 text-sm font-semibold text-background transition hover:opacity-90"
          >
            <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12Z" />
            </svg>
            Star on GitHub
          </a>
          <a
            href="https://github.com/FERAL-AI/FERAL-AI/blob/main/CONTRIBUTING.md"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-xl border border-border px-6 py-3 text-sm font-medium transition hover:bg-card"
          >
            Contributing Guide
          </a>
          <a
            href="https://github.com/FERAL-AI/FERAL-AI/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-xl border border-border px-6 py-3 text-sm font-medium transition hover:bg-card"
          >
            Report Issues
          </a>
        </div>
      </div>
    </section>
  );
}
