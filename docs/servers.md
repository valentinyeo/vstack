# Servers

Two servers. Contabo-UK is the main one. Hetzner is shared.

The same facts live in [config/servers.json](../config/servers.json) for tools that read JSON. Change both in one pull request, or the test fails.

## Contabo-UK, the main server

- IP `80.190.82.74`, hostname `hypertask-vps` (it was `vmi3202882`).
- One user: `valentin`.
- Every chat here is Valentin's own: Multi Bot, Hypertask, vstack, Postbox, Matt Live Stream and the rest.
- From here, `ssh hetzner` or `ssh vps` reaches Hetzner.

## Hetzner, a shared server

- IP `46.224.218.39`, hostname `ubuntu-4gb-nbg1-1`.
- Users: `valentin`, `inne`, `agent`.
- `valentin` is the same Valentin. He runs part of his setup here: local-helper (port 8766, controls his Windows PC) and the Slack reader (triage).
- `inne` is a separate medical company account with its own Claude subscription. Its data stays apart from Valentin's. inne also uses Multi Bot.
- `agent`: an account exists. TODO: its owner says what it is.
- From here, `ssh contabo-uk` or `ssh contabo` reaches Contabo-UK.

## Reading it

- Anything about servers, hosts, ssh, which machine a chat runs on, or inne data: read this file.
- A chat that needs to know where it runs reads this file, not a note from memory. Multi Bot picks a tab's server from `config/servers.json`.
- If an older note puts these two the other way round, this file wins. Fix the note in place; never add a second version.
