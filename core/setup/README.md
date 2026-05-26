# cc setup

Bootstrap cc + cc-studio on a fresh machine.

## Layout assumed by the scripts

```
<source-root>/
├── cc                  # the bash entrypoint
├── lib/
│   ├── db.py
│   ├── studio.py
│   └── tui.py
└── setup/
    ├── setup.sh        # this folder
    ├── setup.ps1
    └── README.md
```

When you run a setup script, it copies these into:

```
~/.cc/
├── lib/db.py
├── lib/studio.py
├── lib/tui.py
├── cache/
├── scripts/
└── setup/

~/.local/bin/cc        # the binary (executable bash)

~/cc-studio/           # canonical workspace ($CC_STUDIO_HOME)
├── projects/          # one folder per project
├── models/            # downloaded HF / external models
├── datasets/          # training data
├── workflows/         # exported workflow YAMLs/JSONs
└── .venv/             # Python venv with streamlit + deps
```

## Linux / macOS

```
bash setup.sh
```

Environment overrides:
- `CC_HOME` — default `~/.cc`
- `CC_STUDIO_HOME` — default `~/cc-studio`
- `INSTALL_BIN` — default `~/.local/bin`
- `SKIP_VENV=1` — skip Python install

After: `cc studio` launches the dashboard.

For system-wide access:
```
sudo ln -s ~/.local/bin/cc /usr/local/bin/cc
```

## Windows

`cc` is bash-first. Either:

1. **WSL2** (recommended) — install Ubuntu/Debian under WSL and run `setup.sh`.
2. **Git for Windows** + PowerShell — install Git which provides bash:
   ```
   winget install --id Git.Git
   pwsh -ExecutionPolicy Bypass -File setup.ps1
   ```

Then run cc through bash:
```
bash %USERPROFILE%\.local\bin\cc studio
```

## Optional: ollama

If you want local models for `cc tiny` and the chat fallback:

```
ollama pull qwen2.5-coder:1.5b    # tiny coder (1 GB, fast)
ollama pull llama3.2              # general purpose (2 GB)
ollama pull kimi-k2.6:cloud       # large fallback for the studio chat
```

Install ollama from <https://ollama.com>.
