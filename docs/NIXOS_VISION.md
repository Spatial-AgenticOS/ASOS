# FERAL as a Native OS Layer: The NixOS Vision

> Engineering specification for packaging FERAL as a first-class NixOS module,
> enabling declarative, reproducible, and rollback-safe deployments.

## 1. What This Is (and What It Is Not)

**This is:** FERAL shipped as a NixOS module (`nixosModules.feral`) that
integrates with the host's systemd, networking, and security stack.

**This is not:** A "FERAL OS" Linux distribution. We do not fork NixOS,
replace its init system, or brand a desktop environment. The host remains
a standard NixOS installation. FERAL is a service layer, like PostgreSQL
or Nginx — declared in `configuration.nix` and managed by `nixos-rebuild`.

The existing `flake.nix` already provides `nixosModules.feral-brain` as a
minimal service unit. This spec defines the full production-grade module.

---

## 2. Declarative Configuration

### 2.1 Module Interface

A site operator writes this in their NixOS `configuration.nix`:

```nix
{
  imports = [ inputs.feral.nixosModules.feral ];

  services.feral = {
    enable = true;

    brain = {
      enable = true;
      host = "0.0.0.0";
      port = 9090;
      llmProvider = "ollama";
      llmModel = "llama3";
      publicBaseUrl = "https://feral.warehouse-east.internal";
      stateDir = "/var/lib/feral";
      extraEnv = {
        FERAL_VISION_ENABLED = "true";
        FERAL_MAX_TIER = "dangerous";
      };
    };

    daemons = {
      robot-zone-a = {
        enable = true;
        package = pkgs.feral-daemon-robot;
        brainUrl = "wss://feral.warehouse-east.internal/v1/node";
        deviceId = "robot-zone-a-01";
        configFile = ./robot-zone-a.yaml;
      };
      camera-cluster = {
        enable = true;
        package = pkgs.feral-daemon-camera;
        brainUrl = "wss://feral.warehouse-east.internal/v1/node";
        deviceId = "cam-cluster-01";
        configFile = ./camera-cluster.yaml;
      };
    };

    providers = {
      ollama = {
        enable = true;
        models = [ "llama3" "llava" ];
        acceleration = "cuda";
      };
    };

    security = {
      mtls.enable = true;
      mtls.caFile = ./pki/ca.pem;
      mtls.certFile = ./pki/brain.pem;
      mtls.keyFile = config.age.secrets.brain-key.path;
      readOnlyRootfs = true;
      hardwareKeyStorage = true;
    };

    updates = {
      channel = "stable";
      autoUpdate = true;
      rollbackOnFailure = true;
    };
  };
}
```

### 2.2 What the Module Generates

From the above declaration, the module produces:

- `systemd.services.feral-brain` — the Brain process
- `systemd.services.feral-daemon-robot-zone-a` — robot daemon
- `systemd.services.feral-daemon-camera-cluster` — camera daemon
- `systemd.services.ollama` — local LLM provider (if enabled)
- `systemd.tmpfiles.rules` — creates `/var/lib/feral` with correct ownership
- `networking.firewall.allowedTCPPorts` — opens port 9090 (configurable)
- `security.pki.certificateFiles` — adds the CA to the system trust store
- `environment.etc."feral/runtime.env"` — rendered environment file

---

## 3. systemd Hardening

Every FERAL unit runs with defense-in-depth systemd directives.

### 3.1 Brain Service Unit

```ini
[Service]
Type=notify
ExecStart=${feralBrainPackage}/bin/feral-brain
EnvironmentFile=/etc/feral/runtime.env

# Filesystem isolation
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/feral /var/log/feral
PrivateTmp=true
NoNewPrivileges=true

# Cgroup resource limits
MemoryMax=4G
CPUQuota=200%
TasksMax=512

# Network
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
IPAddressDeny=any
IPAddressAllow=localhost
IPAddressAllow=10.0.0.0/8

# Capabilities
CapabilityBoundingSet=
AmbientCapabilities=

# Sandboxing
SystemCallFilter=@system-service
SystemCallArchitectures=native
LockPersonality=true
ProtectClock=true
ProtectKernelModules=true
ProtectKernelTunables=true
ProtectKernelLogs=true
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
PrivateDevices=true
```

### 3.2 Daemon Service Units

Daemon units inherit the same hardening plus additional restrictions:

```ini
# Daemons may need hardware access (GPIO, USB, serial)
PrivateDevices=false
DeviceAllow=/dev/ttyUSB* rw
DeviceAllow=/dev/video* r

MemoryMax=1G
CPUQuota=100%
TasksMax=128

# Restart policy
Restart=on-failure
RestartSec=5
WatchdogSec=30
```

If the daemon fails to send a watchdog ping within `WatchdogSec`, systemd
kills and restarts it — no Brain intervention required.

### 3.3 Resource Limits Summary

| Unit | MemoryMax | CPUQuota | TasksMax | Restart |
|:-----|:----------|:---------|:---------|:--------|
| `feral-brain` | 4 GB | 200% | 512 | on-failure (10s) |
| `feral-daemon-*` | 1 GB | 100% | 128 | on-failure (5s) |
| `ollama` | 8 GB | 400% | 256 | on-failure (15s) |

Operators override these via `services.feral.brain.systemd.serviceConfig`
in their NixOS config.

---

## 4. Immutable Builds

### 4.1 Reproducibility

The Nix store guarantees that `nix build .#feral-brain` produces a
byte-identical output given the same `flake.lock` inputs. This means:

- The Brain binary running in production is the exact artifact that passed CI.
- No `pip install` drift, no implicit system library version changes.
- `nix diff-closures` shows the exact dependency delta between two builds.

### 4.2 Rollback on Failure

```
nixos-rebuild switch --flake .#warehouse-east
```

If the new Brain fails its health check (`GET /health` returns non-200
within 60 seconds of activation), the NixOS activation script automatically
rolls back to the previous generation:

```nix
systemd.services.feral-brain.postStart = ''
  timeout 60 bash -c 'until curl -sf http://localhost:9090/health; do sleep 2; done' \
    || (echo "Health check failed, rolling back"; nixos-rebuild switch --rollback)
'';
```

### 4.3 Verified Updates

Update artifacts are signed with an Ed25519 key. The NixOS module
validates signatures before activation:

```
Nix binary cache (Cachix / self-hosted)
  └─ signed with deploy key
      └─ NixOS host verifies signature via trusted-public-keys
          └─ Activation: systemctl restart feral-brain
```

---

## 5. Device Provisioning

### 5.1 Per-Deployment NixOS Configs

A warehouse deployment is a NixOS flake that composes the FERAL module
with site-specific configuration:

```
warehouse-fleet/
├── flake.nix              # inputs: nixpkgs, feral
├── flake.lock
├── hosts/
│   ├── brain-01.nix       # Brain + Ollama on GPU server
│   ├── edge-robot-a.nix   # Robot daemon on Jetson Orin
│   └── edge-cameras.nix   # Camera daemon on x86 NUC
├── pki/
│   ├── ca.pem
│   └── ...
└── secrets/
    └── secrets.age         # age-encrypted credentials
```

Each host file imports `feral.nixosModules.feral` and declares only the
services relevant to that machine. A single `nix build .#nixosConfigurations.edge-robot-a`
produces a complete bootable image for that edge node.

### 5.2 SD Card / USB Provisioning

For headless edge devices:

```bash
nix build .#nixosConfigurations.edge-robot-a.config.system.build.sdImage
dd if=result/sd-image/*.img of=/dev/sdX bs=4M status=progress
```

The device boots, connects to the network, authenticates to the Brain
with its provisioned mTLS cert, and begins operating. No manual SSH
setup required.

---

## 6. Comparison: Docker vs Bare Metal vs NixOS

| Dimension | Docker Compose | Bare Metal (pip) | NixOS Module |
|:----------|:---------------|:-----------------|:-------------|
| **Reproducibility** | Partial (base image updates, layer cache) | None (system Python, pip resolver) | Full (Nix store hash) |
| **Rollback** | Manual (`docker compose down && up` with old tag) | Manual (virtualenv swap) | Atomic (`nixos-rebuild switch --rollback`) |
| **System integration** | Isolated (port mapping, volume mounts) | Full but fragile | Full and declarative |
| **Hardware access** | `--device` flags, `--privileged` | Direct | `DeviceAllow=` directives |
| **Resource limits** | Docker cgroups | None by default | systemd cgroups (fine-grained) |
| **Security** | Container namespace | Host-level user permissions | systemd sandboxing + read-only rootfs |
| **Multi-service** | docker-compose.yml | Multiple systemd units (hand-written) | Single `configuration.nix` |
| **Secrets** | Docker secrets / `.env` file | `.env` file | `agenix` / `sops-nix` (encrypted at rest, decrypted at activation) |
| **Update mechanism** | Pull new image tag | `pip install --upgrade` | `nixos-rebuild switch` with signature verification |
| **Edge deployment** | Requires Docker runtime (~300 MB) | Requires Python runtime | Self-contained NixOS image |

### Key Advantage

NixOS treats the entire system — kernel, services, configs, secrets — as a
single atomic unit. A Docker deployment manages containers but not the host
they run on. Bare metal manages nothing. NixOS manages everything.

---

## 7. Migration Path: Docker to NixOS

For teams currently running FERAL via `docker compose`:

### Phase 1: Nix Dev Shell (Week 1)

- Install Nix on developer machines.
- Use `nix develop` for local development (replaces `pip install -e .`).
- Docker Compose continues to run in CI and production.

### Phase 2: Nix Build in CI (Week 2-3)

- CI builds the FERAL packages with `nix build`.
- Artifacts are pushed to a binary cache (Cachix or self-hosted Nix cache).
- Docker images are still the deployment artifact, but built FROM the Nix output.

### Phase 3: NixOS Test VM (Week 4)

- Provision a NixOS VM (or `nixos-rebuild` an existing machine).
- Import `feral.nixosModules.feral`, configure Brain + one daemon.
- Run integration tests against the NixOS deployment.

### Phase 4: Edge Nodes (Week 5-6)

- Flash edge devices with NixOS images.
- Each device gets a host-specific config from the fleet flake.
- Validate mTLS, watchdog restarts, rollback.

### Phase 5: Full Cutover (Week 7-8)

- Brain servers migrate from Docker to NixOS.
- Docker Compose files archived but retained for fallback.
- `nixos-rebuild switch` becomes the deployment command.

---

## 8. Security

### 8.1 Read-Only Root Filesystem

When `services.feral.security.readOnlyRootfs = true`:

- The NixOS root is mounted read-only (standard NixOS behavior).
- `/var/lib/feral` is the only writable path for the Brain.
- `/tmp` is a private tmpfs per service.
- No attacker who compromises the Brain process can modify system binaries.

### 8.2 Attestation

On devices with TPM 2.0:

```
Boot → TPM measures kernel + initrd + NixOS system closure hash
     → Measured boot log available to Brain for self-attestation
     → Brain reports its closure hash to the Control Plane
     → Control Plane verifies hash matches the expected build
```

If the hash mismatches, the Control Plane refuses to issue the device's
mTLS cert renewal, effectively quarantining the device.

### 8.3 Hardware Key Storage

When `services.feral.security.hardwareKeyStorage = true`:

- mTLS private keys are stored in the TPM or a PKCS#11 token.
- The key never exists in the filesystem — OpenSSL engine loads it
  directly from the hardware module.
- `NODE_API_KEY` is replaced by mTLS; no shared secrets.

### 8.4 Secret Management

Secrets (API keys, database passwords) use `agenix`:

```nix
age.secrets.openai-key = {
  file = ./secrets/openai-key.age;
  owner = "feral";
  group = "feral";
  mode = "0400";
};
```

The secret is encrypted at rest in the Git repo, decrypted at NixOS
activation time, and mounted as a file readable only by the `feral` user.
The LLM provider reads the key from the file path, not an environment
variable — preventing accidental exposure in process listings.

---

## 9. Architecture Diagram

```mermaid
flowchart TD
    subgraph NixOS Host
        subgraph systemd
            SB[feral-brain.service]
            SD1[feral-daemon-robot.service]
            SD2[feral-daemon-camera.service]
            SO[ollama.service]
        end

        subgraph Nix Store
            NB[/nix/store/...-feral-brain]
            ND[/nix/store/...-feral-daemon]
            NO[/nix/store/...-ollama]
        end

        subgraph Security
            TPM[TPM 2.0]
            MTLS[mTLS Certs]
            AGE[agenix Secrets]
        end

        VAR[/var/lib/feral — state]
        LOG[/var/log/feral — logs]
    end

    subgraph Hardware
        USB[USB / Serial Devices]
        CAM[Cameras]
        GPIO[GPIO / Motor Controllers]
    end

    SB --> NB
    SD1 --> ND
    SD2 --> ND
    SO --> NO

    SB -->|state| VAR
    SB -->|logs| LOG
    SD1 -->|logs| LOG

    SD1 --> USB
    SD1 --> GPIO
    SD2 --> CAM

    SB <-->|wss| SD1
    SB <-->|wss| SD2
    SB <-->|http| SO

    TPM --> MTLS
    AGE --> SB
    AGE --> SO

    style TPM fill:#f96,stroke:#333
    style VAR fill:#9cf,stroke:#333
```

### Unit Dependency Chain

```
multi-user.target
  └─ feral-brain.service (After=network-online.target ollama.service)
      ├─ feral-daemon-robot.service (After=feral-brain.service)
      └─ feral-daemon-camera.service (After=feral-brain.service)
```

Daemons wait for the Brain to pass its health check before starting.
If the Brain restarts, daemons reconnect automatically via their
WebSocket retry loop (existing behavior in the daemon SDK).

---

## 10. Testing the NixOS Module

### 10.1 NixOS VM Tests

NixOS provides a built-in VM test framework:

```nix
nixosTest {
  name = "feral-integration";
  nodes = {
    brain = { imports = [ feral.nixosModules.feral ]; services.feral.brain.enable = true; };
    edge  = { imports = [ feral.nixosModules.feral ]; services.feral.daemons.test-sensor.enable = true; };
  };
  testScript = ''
    brain.wait_for_unit("feral-brain.service")
    brain.wait_for_open_port(9090)
    brain.succeed("curl -sf http://localhost:9090/health | grep ok")

    edge.wait_for_unit("feral-daemon-test-sensor.service")
    brain.succeed("curl -sf http://localhost:9090/api/devices | grep test-sensor")
  '';
}
```

This spins up QEMU VMs, boots NixOS, starts the services, and runs
assertions — fully automated in CI with no Docker dependency.

### 10.2 Nix Flake Check

```bash
nix flake check   # runs all NixOS tests + package builds
```

---

## 11. Open Questions

1. **Darwin support**: macOS cannot run NixOS, but `nix-darwin` supports
   `launchd` services. Should we provide a parallel `darwinModules.feral`
   for macOS development machines?
2. **ARM edge devices**: NixOS supports `aarch64-linux` (Raspberry Pi,
   Jetson). Cross-compilation or native builds on-device?
3. **Nix cache hosting**: Self-hosted Attic vs Cachix for the binary cache?
4. **Flake registry**: Should `feral` be published to the Nix flake registry
   so users can `nix run feral#brain` without cloning the repo?
