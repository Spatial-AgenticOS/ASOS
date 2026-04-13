const FEATURES = [
  {
    icon: "🧠",
    title: "Persistent Memory",
    desc: "Four tiers — working, episodic, semantic, execution log. Knowledge graph. Your AI remembers your entire life, not just the current session.",
  },
  {
    icon: "🎙️",
    title: "Sub-200ms Voice",
    desc: "Wake word detection, OpenAI Realtime + Gemini Live streaming, interrupt-and-resume. Three voice paths for every use case.",
  },
  {
    icon: "🏠",
    title: "Hardware Mesh",
    desc: "Direct Bluetooth/local control of lights, sensors, wristbands, smart glasses, robots. No cloud roundtrip. 12+ device types.",
  },
  {
    icon: "🤖",
    title: "Proactive Intelligence",
    desc: "FERAL doesn't wait. It watches your screen, health, calendar — and speaks up when it has something valuable to say.",
  },
  {
    icon: "🎨",
    title: "Server-Driven UI",
    desc: "The brain generates UI dynamically — charts, forms, cards, alerts — and pushes them to whatever screen you're looking at.",
  },
  {
    icon: "🔒",
    title: "Three Autonomy Levels",
    desc: "Strict, hybrid, or loose. Real enforcement via ApprovalManager + safety classification. Not just a config flag.",
  },
];

export default function FeatureGrid() {
  return (
    <section className="border-t border-border px-6 py-20 sm:py-28">
      <div className="mx-auto max-w-5xl">
        <h2 className="text-center text-3xl sm:text-4xl font-black tracking-tight">
          What it does
        </h2>
        <p className="mt-4 text-center text-muted">
          Not promises. Shipped code.
        </p>

        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="rounded-2xl border border-border bg-card p-6 transition hover:border-accent"
            >
              <div className="text-3xl">{f.icon}</div>
              <h3 className="mt-3 text-lg font-bold">{f.title}</h3>
              <p className="mt-2 text-sm text-muted leading-relaxed">
                {f.desc}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
