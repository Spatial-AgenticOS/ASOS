export default function Footer() {
  return (
    <footer className="border-t border-border px-6 py-10">
      <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-6 sm:flex-row">
        <div className="flex items-center gap-3">
          <span className="text-lg font-black">FERAL</span>
          <span className="text-sm text-muted">Unleashed AI</span>
        </div>

        <nav className="flex flex-wrap items-center gap-6 text-sm text-muted">
          <a
            href="https://github.com/FERAL-AI/FERAL-AI"
            target="_blank"
            rel="noopener noreferrer"
            className="transition hover:text-foreground"
          >
            GitHub
          </a>
          <a
            href="https://github.com/FERAL-AI/FERAL-AI/blob/main/CONTRIBUTING.md"
            target="_blank"
            rel="noopener noreferrer"
            className="transition hover:text-foreground"
          >
            Contribute
          </a>
          <a
            href="https://github.com/FERAL-AI/FERAL-AI/blob/main/LICENSE"
            target="_blank"
            rel="noopener noreferrer"
            className="transition hover:text-foreground"
          >
            Apache 2.0
          </a>
        </nav>

        <p className="text-xs text-muted">
          Made with spite and good intentions.
        </p>
      </div>
    </footer>
  );
}
