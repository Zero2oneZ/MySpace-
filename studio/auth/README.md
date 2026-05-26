# studio/auth — friend-scoped access control

The studio apps (Wardrobe, DAG canvas, YouTube cutter) are designed for
**personal GPU sharing with a known small group of friends** — NOT a
public service. This module is the auth layer that gates those apps.

## What this is

A two-factor access model:

1. **SSH layer (network)** — friends connect via an SSH reverse tunnel.
   Their pubkey is whitelisted in `~/.ssh/authorized_keys` with strict
   `command="…", no-pty, permitlisten` restrictions, so even with the
   key they can ONLY port-forward to the studio ports — never get a
   shell.
2. **App layer (this module)** — once tunneled in, the friend hits a
   Streamlit login page. Their **username** is looked up in
   `permissions.jsonl`. On first successful login, their **client IP**
   is hashed (`sha256(user + ":" + ip)`) and bound to the row.
   Subsequent logins MUST come from the same IP.

That's the entire security model. It is intentionally simple.

## What this is NOT

- **Not enterprise auth.** No OAuth, no MFA, no rate limiting, no audit
  log beyond `first_seen / last_seen`.
- **Not a public service.** If you expose port 8510 to the open
  internet, all bets are off.
- **Not password-strong.** Every friend's password is the literal string
  `"passwd"`. The strong factor is SSH key + IP binding, not the password.

If you want enterprise auth, this isn't it.

## Permissions store: `permissions.jsonl`

One JSON row per friend, written by `seed_permissions.py` or
`cc -auth-grant`. Schema:

```json
{
  "user":           "Jamie",
  "permission":     true,
  "passwd_hash":    "<sha256 of plaintext>",
  "email":          "friends@Tmail.com",
  "solo":           false,
  "loopback_only":  false,
  "ip_bound":       null,
  "bind_hash":      null,
  "first_seen":     null,
  "last_seen":      null
}
```

- `loopback_only: true` — the row only accepts requests from `127.0.0.1`
  or `::1`. Used for the `localhost` admin row.
- `solo: true` — username is null; matched by email instead. Used for
  the `friends@Tmail.com` fallback when a feature wants an email-only
  entry path.
- `ip_bound` / `bind_hash` / `first_seen` — null until the first
  successful login. Once set, they're read-only via the gate. Only
  `cc -auth-revoke <user>` clears them.

The file lives at `studio/auth/permissions.jsonl`, is mode 600, and is
**git-ignored** — it is per-host state, not source.

## Onboarding a new friend (Tom's side)

```bash
# 1. Get their SSH public key (one-line, ssh-ed25519 or ssh-rsa).
#    e.g. they email you ~/.ssh/id_ed25519.pub

# 2. Authorize their key (port-forward-only, no shell).
cc -auth-ssh add Bronco ~/Downloads/bronco.pub
# (or, equivalent):
studio/auth/ssh_friend_setup.sh add Bronco ~/Downloads/bronco.pub

# 3. (Optional) add them to permissions.jsonl. The seed list already
#    has Jamie / Bronco / Pete / Ashley pre-baked, so skip this for
#    those four. For a brand-new friend:
cc -auth-grant Mike

# 4. Tell them their username + send them the SSH command:
cc -auth-ssh share Bronco
```

Bronco then runs the printed `ssh -L 8510:localhost:8510 …` command on
his machine, opens `http://localhost:8510` in his browser, enters his
username, and his IP gets bound on first login.

## Revoking a friend

```bash
# Clear their IP binding (lets them log in fresh from a new IP — or, if
# you also remove their SSH key, blocks them entirely):
cc -auth-revoke Bronco

# Remove their SSH key:
cc -auth-ssh revoke Bronco
```

Both steps. Don't forget the SSH revoke — if you only clear the IP
binding, they can still tunnel in (and log in from a new IP).

## Solo email mode

A `friends@Tmail.com` row exists with `user: null, solo: true`. Any
feature that wants to allow email-only entry can call:

```python
from auth.gate import verify
res = verify(user=None, passwd=None, client_ip=req_ip, email="friends@Tmail.com")
if res.ok:  # solo session granted
    ...
```

The solo row is IP-bound on its first successful login too — so only one
network can use it at a time. Use `cc -auth-revoke` on the `(solo)`
pseudo-user to rotate it (though the CLI shows it as a hyphen — the
shorthand is `cc -auth-revoke '(solo)'` — actually you need to clear it
by editing permissions.jsonl directly today; this is a known gap).

## Admin reference

```text
cc -auth-seed              # regenerate permissions.jsonl from SEED list
cc -auth-list              # pretty-print all rows
cc -auth-status            # one-line counts (bound / unbound / solo)
cc -auth-grant <user>      # add a new friend (default passwd="passwd")
cc -auth-revoke <user>     # clear that user's IP binding
cc -auth-ssh <subcmd>      # passthrough to ssh_friend_setup.sh
```

## Why this design

- **SSH key + IP binding** is what real attackers would have to defeat
  *together*, not the password. A weak password is fine when the door
  is already SSH-gated and the IP is sticky.
- **Sticky IPs** assume friends mostly connect from a home network — if
  they change networks, Tom clears the binding once. This is a tradeoff
  in favor of detecting session theft over user convenience.
- **JSONL** because: human-readable, easy to migrate, no DB to set up,
  one append per state change. Files this small don't need SQLite.
- **`localhost` row** has no passwd because the gate only accepts it
  from `127.0.0.1`, so the network layer is already restrictive enough.

## Files

- `gate.py` — verify() (pure) + require_login() (Streamlit gate)
- `seed_permissions.py` — generates / refreshes permissions.jsonl
- `ssh_friend_setup.sh` — manage authorized_keys for friend SSH grants
- `test_gate.py` — 10 unit tests covering every documented path
- `permissions.jsonl` — generated, mode 600, git-ignored
