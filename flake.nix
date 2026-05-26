{
  description = "MySpace++ — deterministic terminal substrate for AI orchestration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          # MySpace++ is proprietary — see LICENSE. `nix build` requires
          # NIXPKGS_ALLOW_UNFREE=1 to acknowledge non-OSI licensing.
          config.allowUnfree = true;
        };

        # Runtime dependencies. Every binary cc / myspace might invoke at
        # any code path must be in this list, so the wrapped PATH is
        # self-sufficient regardless of the user's environment.
        runtimeDeps = with pkgs; [
          bash
          python3            # sqlite3 module is built-in
          jq
          curl
          sqlite             # `sqlite3` CLI used by smoke tests
          coreutils          # sha256sum, mktemp, cat, dirname, basename, date
          gawk
          gnused
          gnugrep
          util-linux         # uuidgen fallback
        ];

      in {
        packages.myspace = pkgs.stdenv.mkDerivation {
          pname = "myspace-pp";
          version = "0.1.0";

          src = ./.;

          nativeBuildInputs = [ pkgs.makeWrapper ];
          buildInputs = runtimeDeps;

          # No build phase — we're just packaging scripts.
          dontBuild = true;
          dontConfigure = true;

          installPhase = ''
            mkdir -p $out/bin $out/share/myspace-pp
            cp -r core/. $out/share/myspace-pp/
            chmod +x $out/share/myspace-pp/cc
            chmod +x $out/share/myspace-pp/tests/*.sh
            chmod +x $out/share/myspace-pp/setup/*.sh

            # Wrap with a guaranteed PATH so the script never fails on a
            # missing binary regardless of the user's environment. Also
            # pin CC_INSTALL_ROOT so the script's auto-discovery never
            # has to guess on Nix's symlink-heavy filesystem.
            makeWrapper $out/share/myspace-pp/cc $out/bin/myspace \
              --prefix PATH : ${pkgs.lib.makeBinPath runtimeDeps} \
              --set CC_INSTALL_ROOT $out/share/myspace-pp

            # Keep `cc` as an alias for users coming from the original
            # tool. Same wrapper, different name.
            ln -s $out/bin/myspace $out/bin/cc
          '';

          meta = with pkgs.lib; {
            description = "Deterministic terminal substrate for AI orchestration";
            longDescription = ''
              MySpace++ packages the cc terminal manager for cross-OS
              deployment. Deterministic small-model dispatch with sha256
              caching, two-DB scope discipline, agent lifecycle tracking,
              swarm/workflow/phase orchestration. Designed as the substrate
              under which frontier model adapters (Claude, Codex, HF
              Spaces) layer as escalation paths.
            '';
            homepage = "https://github.com/zero2onez/MySpace-pp";
            license = licenses.unfree;  # Proprietary — see LICENSE
            platforms = platforms.unix;
            maintainers = [ ];
          };
        };

        packages.default = self.packages.${system}.myspace;

        apps.myspace = {
          type = "app";
          program = "${self.packages.${system}.myspace}/bin/myspace";
        };
        apps.default = self.apps.${system}.myspace;

        # `nix develop` for contributors — same deps as runtime plus
        # linters and a sourced shellHook that puts ./core/cc on PATH.
        devShells.default = pkgs.mkShell {
          buildInputs = runtimeDeps ++ (with pkgs; [
            shellcheck
            shfmt
            python3Packages.streamlit  # for `myspace studio` in dev
          ]);

          shellHook = ''
            echo "MySpace++ dev shell — repo root: $PWD"
            export CC_INSTALL_ROOT="$PWD/core"
            export PATH="$PWD/core:$PATH"
            alias myspace="$PWD/core/cc"
            echo "  myspace -help    → $PWD/core/cc -help"
            echo "  smoke tests      → ./core/tests/smoke.sh"
            echo "  determinism      → ./core/tests/determinism.sh"
          '';
        };

        # `nix flake check` runs this — smoke test as a derivation.
        checks.smoke = pkgs.runCommand "myspace-smoke" {
          buildInputs = runtimeDeps;
        } ''
          export CC_HOME=$TMPDIR/.cc-home
          export CC_CACHE=$CC_HOME/cache
          export CC_GLOBAL_DB=$CC_HOME/cc.db
          export CC_BIN=${self.packages.${system}.myspace}/bin/myspace
          mkdir -p $CC_HOME

          cp -r ${./core}/tests $TMPDIR/tests
          chmod +x $TMPDIR/tests/smoke.sh

          $TMPDIR/tests/smoke.sh > $out
        '';
      });
}
