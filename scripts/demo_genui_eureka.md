# FERAL Gen-UI App Store — Live Demo Talk Track

> Companion to `scripts/demo_genui_eureka.sh`. Read the column that fits
> the audience. Time per act is what the script actually paces; you can
> stretch with the talk track or compress with `--auto`.

## Pre-flight (do this BEFORE the audience walks in)

```bash
cd /Users/mahmoudomar/Desktop/thoera-mac/ASOS

# Terminal A — brain (leave it running)
feral serve

# Terminal B — mock mobility API (leave it running)
cd /Users/mahmoudomar/Desktop/test-app/uber-genui-demo/mock-api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m uvicorn main:APP --host 127.0.0.1 --port 8765

# Terminal C — one-time publisher bootstrap (do NOT do this onstage)
feral publisher login        # GitHub OAuth, opens a browser
feral publisher register     # Ed25519 keygen + register pubkey

# Reviewer browser session — sign in to https://admin.feral.sh/review/queue
# in a tab that's already authenticated. We do NOT want to demo TOTP setup.

# Sanity:
bash scripts/demo_genui_eureka.sh --check
```

## Live demo (the recorded version)

```bash
# Terminal C — the only one you touch onstage
bash scripts/demo_genui_eureka.sh
# (or --auto for a continuous video take)
```

The script paces itself. Read the column below as each act runs.

---

## ACT 1 — PUBLISHER (~60 s)

**On screen:** `feral app validate` → `build` → `publish`. Output ends with an `item_id` and the line `submission received, pending review`.

| Investor framing | Developer framing |
|---|---|
| "This is the moment a third-party developer ships into FERAL — *no native app, no SDK lock-in*. They published a manifest, a skill, and authored UI surfaces. Same artifact runs on every FERAL device the user owns." | "The bundle is a manifest, action contracts, JSON-Schema for every payload, an Ed25519-signed tarball, and a Python skill that the agent can call headlessly OR that GenUI can resolve via `skill_call` actions. One contract, two consumers." |
| "Our marketplace is open. Anyone with a GitHub account can publish — but it doesn't ship to users yet." | "`feral publish` posts a multipart bundle to `/api/v1/publish` on the registry. The signature is verified server-side. Status lands `submitted/private`." |

**Pause beat:** "And here's the part everyone gets wrong about open marketplaces."

---

## ACT 2 — FAIL CLOSED (~30 s)

**On screen:** `curl /api/apps/install` returns **HTTP 422** with `error: "registry_item_not_approved"`.

| Investor framing | Developer framing |
|---|---|
| "If a user tried to install this right now — *they can't.* The registry refuses. The brain refuses. There's no path. Open marketplace, FERAL-controlled gate. That's the moat." | "The registry's `/blobs/{sha}` endpoint returns 404 to anonymous traffic for non-approved items. Catalog hides them. AppRegistry adds a defence-in-depth check: even if a stray response leaks `status: submitted` it refuses the install before bytes hit disk." |
| "This is what the App Store sells. We just shipped it for an open AI marketplace, in a week." | "Override exists for internal staging — `FERAL_INTERNAL_ALLOW_UNAPPROVED=1` env *and* `internal_override=true` on the request. Both required. Neither alone bypasses the gate." |

**Pause beat:** "The gate is real. So who decides what crosses it?"

---

## ACT 3 — REVIEWER (~45–90 s, depending on mode)

**On screen:** Browser tab on `https://admin.feral.sh/review/queue`. Submission visible. Sign in with username + password + TOTP. Click Approve. The shell script polls and continues automatically.

| Investor framing | Developer framing |
|---|---|
| "FERAL reviewers — that's us — sit on a separate domain, behind per-user accounts and a real second factor. Every action is recorded with the reviewer's name and timestamp. *This is the org's seat at the table.*" | "`admin.feral.sh` is the same Render service as `feral.sh` but middleware-isolated by host header. Reviewer auth is scrypt-hashed passwords + RFC 6238 TOTP, separate scope from the publisher JWT pipeline. Every approve/reject writes a row to `review_events` keyed by reviewer username." |
| "Today it's me clicking. Tomorrow it's a team. Eventually it's an automated review pipeline plus human escalation. The contract doesn't change." | "The proxy on feral.sh injects the registry reviewer secret server-side; the browser never sees it. We can swap the per-user auth for full GitHub-org OAuth without changing the registry-side API." |

**Pause beat:** "The instant that approval lands…"

---

## ACT 4 — USER (~45 s)

**On screen:** The same `curl /api/apps/install` from Act 2 — now returns **HTTP 200**. Then `/open` and `/dispatch` show the surface and the action result.

| Investor framing | Developer framing |
|---|---|
| "Same command, same user, same client version. The gate let it through. The user installs, opens the surface, taps an action, and the publisher's API responds — all without the user knowing the gate even existed." | "The registry's `/item/{id}` flipped from 404 to 200, our acceptance check on the brain side allows the install, `install_from_dir` writes the bundle into `~/.feral/apps/<app_id>/`, the surface registers, and `/dispatch` resolves `action_id=home_get_estimate` to `skill_call uber_demo__estimate` against the publisher's mock API." |
| "End-to-end: a third-party app, on a real user's brain, after a real org review, with a real audit trail. *Two minutes.*" | "Cost: zero new infrastructure, zero registry restarts. The gate is the data layer. Adding a new gate (e.g. payment, signing-key rotation) is one column on `items`, one route on the registry, one branch in `install_from_registry`." |

**Pause beat (final):** "That's the eureka. Open marketplace, FERAL gate, full audit. Ours from kernel to UI."

---

## Recovery / failure modes (memorize)

| If you see… | Say… | Then do… |
|---|---|---|
| `registry unreachable` during preflight | "Pre-flight caught the network issue, the demo never starts in a broken state — that's the whole point of pre-flight." | Cancel, fix DNS/firewall, restart. |
| Publish step prints a 412 about pubkey | "First-time publisher needs to register a key — pre-baked for the demo." | Run `feral publisher register` once, retry. (You should never hit this onstage if you ran pre-flight.) |
| `expected 422, got 200` after publish | (don't say anything funny — this is bad) | Stop the demo. The acceptance gate is broken; investigate before publicly demoing. |
| Reviewer browser doesn't show the submission | "Reviewer queue polls every few seconds; give the registry a moment." | Refresh the page. If still missing, check `FERAL_REGISTRY_REVIEWER_SECRET` matches between `feral-registry` (Fly) and `feral-sh` (Render). |
| Dispatch returns 5xx | "The publisher's mock API isn't running — that's a service the *publisher* owns, not FERAL. In production their server is just up." | Restart the mock API; or skip dispatch and conclude on `/open` showing the surface. |

## After the demo

```bash
# Reset for the next take
bash scripts/demo_genui_eureka.sh --reset

# Or if you ran with --auto and want to re-record cleanly:
# - the brain still has the install; --reset uninstalls it
# - the registry row stays (immutable). Subsequent --auto runs will publish
#   a NEW item_id at the same kind+name+(bumped version) -- bump version
#   in manifest.yaml first, or accept the 409 conflict and re-publish.
```

## What is *not* in this demo (be honest if asked)

- No real driver matching, payments, or external mobility APIs in the publisher app — it's a faithfully-shaped mock so the *contract* shows correctly.
- The user-side install runs on the demo machine's local brain. We're not demoing remote install across a paired phone here; that's a separate end-to-end story.
- Approval is a single click for one reviewer. Multi-reviewer + signed approval flows are on the roadmap.
- The TOTP setup is pre-baked. We don't enroll a new reviewer onstage.
