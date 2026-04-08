{
  description = "THEORA thin Nix foundation (brain + client + dev shell)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
    in
    (flake-utils.lib.eachSystem systems
      (system:
        let
          pkgs = import nixpkgs { inherit system; };
          python = pkgs.python311;
          node = pkgs.nodejs_20;
        in
        {
          packages = rec {
            theora-brain = pkgs.writeShellApplication {
              name = "theora-brain";
              runtimeInputs = [ python node pkgs.git ];
              text = ''
                export THEORA_HOME="${THEORA_HOME:-$HOME/.theora}"
                export THEORA_HOST="${THEORA_HOST:-0.0.0.0}"
                export THEORA_PORT="${THEORA_PORT:-9090}"
                if [ -z "${THEORA_PUBLIC_BASE_URL:-}" ]; then
                  export THEORA_PUBLIC_BASE_URL="http://localhost:$THEORA_PORT"
                fi
                cd ${self}/asos-core
                exec ${python}/bin/python -m cli.main serve --bind "$THEORA_HOST" --serve-port "$THEORA_PORT"
              '';
            };

            theora-client = pkgs.writeShellApplication {
              name = "theora-client";
              runtimeInputs = [ node ];
              text = ''
                cd ${self}/asos-client
                if [ ! -d node_modules ]; then
                  echo "node_modules not found. Run: npm install"
                  exit 1
                fi
                exec ${node}/bin/npm run dev -- --host
              '';
            };

            default = theora-brain;
          };

          apps = {
            brain = {
              type = "app";
              program = "${self.packages.${system}.theora-brain}/bin/theora-brain";
            };
            client = {
              type = "app";
              program = "${self.packages.${system}.theora-client}/bin/theora-client";
            };
            default = {
              type = "app";
              program = "${self.packages.${system}.theora-brain}/bin/theora-brain";
            };
          };

          devShells.default = pkgs.mkShell {
            packages = [
              python
              node
              pkgs.git
              pkgs.pkg-config
              pkgs.rustc
              pkgs.cargo
            ];
            shellHook = ''
              export THEORA_HOME="${THEORA_HOME:-$HOME/.theora}"
              export THEORA_HOST="${THEORA_HOST:-0.0.0.0}"
              export THEORA_PORT="${THEORA_PORT:-9090}"
              export THEORA_PUBLIC_BASE_URL="${THEORA_PUBLIC_BASE_URL:-http://localhost:$THEORA_PORT}"
              echo "THEORA dev shell ready"
              echo "Run brain: cd asos-core && python -m cli.main serve"
              echo "Run client: cd asos-client && npm install && npm run dev"
            '';
          };
        }))
    // {
      nixosModules.theora-brain = { config, lib, pkgs, ... }:
        let
          cfg = config.services.theora.brain;
        in
        {
          options.services.theora.brain = {
            enable = lib.mkEnableOption "THEORA brain service";
            package = lib.mkOption {
              type = lib.types.package;
              default = self.packages.${pkgs.system}.theora-brain;
              description = "THEORA brain package to execute.";
            };
            host = lib.mkOption {
              type = lib.types.str;
              default = "0.0.0.0";
            };
            port = lib.mkOption {
              type = lib.types.port;
              default = 9090;
            };
            home = lib.mkOption {
              type = lib.types.str;
              default = "/var/lib/theora";
            };
          };

          config = lib.mkIf cfg.enable {
            users.users.theora = {
              isSystemUser = true;
              group = "theora";
              home = cfg.home;
              createHome = true;
            };
            users.groups.theora = { };

            systemd.services.theora-brain = {
              description = "THEORA Brain";
              after = [ "network-online.target" ];
              wantedBy = [ "multi-user.target" ];
              environment = {
                THEORA_HOME = cfg.home;
                THEORA_HOST = cfg.host;
                THEORA_PORT = toString cfg.port;
                THEORA_PUBLIC_BASE_URL = "http://localhost:${toString cfg.port}";
              };
              serviceConfig = {
                ExecStart = "${cfg.package}/bin/theora-brain";
                Restart = "on-failure";
                User = "theora";
                Group = "theora";
                WorkingDirectory = cfg.home;
              };
            };
          };
        };
    };
}
