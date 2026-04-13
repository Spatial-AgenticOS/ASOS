export default function AntiHero() {
  return (
    <section className="border-t border-border px-6 py-20 sm:py-28">
      <div className="mx-auto max-w-4xl">
        <h2 className="text-center text-3xl sm:text-4xl font-black tracking-tight">
          What they built vs. what we built
        </h2>

        <div className="mt-12 grid gap-8 sm:grid-cols-2">
          <div className="rounded-2xl border border-border bg-card p-8">
            <p className="text-sm font-bold uppercase tracking-widest text-muted">
              Big AI (OpenAI, Apple, Google)
            </p>
            <ul className="mt-6 space-y-3 text-sm text-muted">
              <li className="flex gap-2">
                <span className="text-danger">✕</span> Lives on their servers
              </li>
              <li className="flex gap-2">
                <span className="text-danger">✕</span> Forgets between sessions
              </li>
              <li className="flex gap-2">
                <span className="text-danger">✕</span> 2s voice latency, cloud-only
              </li>
              <li className="flex gap-2">
                <span className="text-danger">✕</span> No health monitoring
              </li>
              <li className="flex gap-2">
                <span className="text-danger">✕</span> No smart home control
              </li>
              <li className="flex gap-2">
                <span className="text-danger">✕</span> No proactive intelligence
              </li>
              <li className="flex gap-2">
                <span className="text-danger">✕</span> Open-sourced some weights, called it a day
              </li>
            </ul>
          </div>

          <div className="rounded-2xl border-2 border-accent bg-card p-8">
            <p className="text-sm font-bold uppercase tracking-widest text-accent">
              FERAL
            </p>
            <ul className="mt-6 space-y-3 text-sm">
              <li className="flex gap-2">
                <span className="text-accent">✓</span> Lives on YOUR devices
              </li>
              <li className="flex gap-2">
                <span className="text-accent">✓</span> 4-tier memory + knowledge graph
              </li>
              <li className="flex gap-2">
                <span className="text-accent">✓</span> Sub-200ms voice, 3 providers
              </li>
              <li className="flex gap-2">
                <span className="text-accent">✓</span> Real-time biometrics from wristband
              </li>
              <li className="flex gap-2">
                <span className="text-accent">✓</span> Direct local mesh, no cloud
              </li>
              <li className="flex gap-2">
                <span className="text-accent">✓</span> Rule + LLM hybrid coaching
              </li>
              <li className="flex gap-2">
                <span className="text-accent">✓</span> Brain, client, mobile, SDK, desktop — all open
              </li>
            </ul>
          </div>
        </div>

        <p className="mt-10 text-center text-sm text-muted">
          They built chatbots. We built an AI that actually lives with you.
        </p>
      </div>
    </section>
  );
}
