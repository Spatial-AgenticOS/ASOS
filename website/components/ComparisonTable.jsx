const ROWS = [
  ["Where it runs", "Their servers", "Your terminal", "Your entire device ecosystem"],
  ["Memory", "Forgets between sessions", "Plugin-based", "4-tier + knowledge graph + P2P sync"],
  ["Voice", "2s latency, cloud-only", "Extension-based", "Sub-200ms, wake word, 3 providers"],
  ["Health monitoring", "No", "No", "Real-time biometrics from wristband"],
  ["Smart home", "Cloud API roundtrip", "No", "Direct local mesh, no cloud"],
  ["Proactive intelligence", "No", "No", "Rule + LLM hybrid with coaching"],
  ["Identity / learning", "No", "Workspace files", "SOUL.md + USER.md + auto-learning"],
  ["Autonomy levels", "No", "No", "Strict / Hybrid / Loose"],
  ["GenUI", "No", "Canvas/A2UI", "Full SDUI generation engine"],
  ["Open source", "Weights only", "Yes", "Brain, client, mobile, SDK, desktop"],
];

export default function ComparisonTable() {
  return (
    <section className="border-t border-border px-6 py-20 sm:py-28">
      <div className="mx-auto max-w-5xl">
        <h2 className="text-center text-3xl sm:text-4xl font-black tracking-tight">
          Honest comparison
        </h2>
        <p className="mt-4 text-center text-sm text-muted">
          No marketing BS. Here&apos;s what actually exists.
        </p>

        <div className="mt-10 overflow-x-auto rounded-2xl border border-border">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border bg-card">
                <th className="px-4 py-3 font-medium text-muted">Dimension</th>
                <th className="px-4 py-3 font-medium text-muted">Big AI</th>
                <th className="px-4 py-3 font-medium text-muted">OpenClaw</th>
                <th className="px-4 py-3 font-bold text-accent">FERAL</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map(([dim, big, oc, feral], i) => (
                <tr
                  key={dim}
                  className={i % 2 === 0 ? "" : "bg-card/50"}
                >
                  <td className="px-4 py-3 font-medium">{dim}</td>
                  <td className="px-4 py-3 text-muted">{big}</td>
                  <td className="px-4 py-3 text-muted">{oc}</td>
                  <td className="px-4 py-3 font-semibold">{feral}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
