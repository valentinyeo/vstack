# Identity

Get your own board login. Do it yourself: never ask Valentin, and never print a token.

## One name everywhere

Your Multibot chat name is every name you show:

- the Hypertask agent display name
- your view title and its label
- your Claude Code session title (`/rename`)
- the `label` in a board line, when the chat name is not resolved for you

If your Multibot name is `Hypertask Reconciler`, every one of those reads `Hypertask Reconciler`. No short forms, no second name. A write whose author is not that name is the wrong login.

The board line's label is the chat name, not the repo name (see `views.md` and `sync.md`). Several chats can share one repo.

## Which login

| Role skill | Name | Slug | Boards |
|---|---|---|---|
| support-manager | HT Support Lead | ht-support-lead | 10450, 15 |
| design-lead | HT Design Lead | ht-design-lead | 15 |
| marketing-lead | HT Growth Lead | ht-growth-lead | 2108, 15 |
| finance-lead | HT Finance Lead | ht-finance-lead | 2462 |
| Infra lead | Infra Lead | infra-lead | 11514, 15, 2060 (member only) |
| CI Boss | CI Boss | ci-boss | 11514, 15, 2060 |
| Chief Of Staff | Chief Of Staff | chief-of-staff | 15, 473, 1215, 2060, 2101, 2108, 2128, 2462, 2467, 8783, 10450, 10958, 11514, 11612 |

Any other chat uses its own Multibot name and the board named by its project.

A list read during setup may use the CLI's saved login. Never write with it.

## Token files

```bash
C=~/.config/hypertask-agents/credentials; S=$C/sessions
```

The flat file `$S/<slug>-agent-token` is the one every tool reads. Mode 600.

## Steps

1. **Token already there?** `[ -s $S/<slug>-agent-token ] && echo have`. If yes, decode its agent id and go to step 4.

   ```bash
   python3 - ~/.config/hypertask-agents/credentials/sessions/<slug>-agent-token <<'P'
   import base64, json, sys
   token = open(sys.argv[1]).read().strip().split('.')[1]
   token += '=' * (-len(token) % 4)
   print(json.loads(base64.urlsafe_b64decode(token)).get('agentId', ''))
   P
   ```

2. **Find your agent.** `hypertask --json agents list --query "<your name>"`. Reuse a row with your name and at least one of your boards, or one with no boards. A row that belongs to another team or chat: leave it alone.

3. **Reuse or mint.**

   - A token file exists for that agent id somewhere under `$C`: link it.

     ```bash
     umask 077; mkdir -p "$S/<slug>"; ln -sfn <that file> "$S/<slug>/<slug>-agent-token"
     ```

     Do not rotate it. Rotating kills the other file.

   - No token file: create the agent on your boards, one `--project` per board. It prints the token once, straight into a 600 file.

     ```bash
     umask 077; mkdir -p "$S/<slug>"
     hypertask --json agents create --name "<your name>" --project <board> \
       | python3 -c "import json,sys; d=json.load(sys.stdin); a=d.get('agent') or {}; t=d.get('token') or a.get('token'); open('$S/<slug>/<slug>-agent-token','w').write(t); print('saved', a.get('id',''))"
     chmod 600 "$S/<slug>/<slug>-agent-token"
     ```

   - An existing agent with no token file: `hypertask agents rotate-token --id <agent id>`, saved the same way.

4. **Boards.** You can join any board a teammate is on. Never stop at "agents cannot change their own access". Never ask Valentin to click.

   - Any member of the board adds you. Ask another agent already on it, or run it from that board with any working agent login:

     ```bash
     hypertask project members <board id>
     hypertask project invite <board id> --user <your agent uuid>
     ```

   - With your owner's login (the one that created you), `hypertask agents update --id <agent id> --add-project <board id>` also works. Repeat `--add-project` for more boards.
   - If the reply says agents can only belong to boards in one team, that agent is not yours: remove the links you made, create your own.

5. **Flat link.** `[ -e $S/<slug>-agent-token ] || ln -sfn <slug>/<slug>-agent-token $S/<slug>-agent-token`

6. **Name.** `hypertask agents update --id <agent id> --name "<your name>"` if it differs.

7. **Verify read and write.**

   ```bash
   T=$(cat "$S/<slug>-agent-token")
   hypertask --json --token "$T" context | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['connected_agent']['displayName'], [p['id'] for p in d['projects']])"
   ```

   The name must be yours and every board must be listed.

   Write check, per board: make a draft comment on any ticket there, then delete it.

   ```bash
   K=$(hypertask --json --token "$T" task list --project <board> --limit 1 | python3 -c "import json,sys; t=json.load(sys.stdin).get('tasks') or [{}]; print(t[0].get('ticketNumber',''))")
   D=$(hypertask --json --token "$T" draft create "$K" --comment --text "identity check" | python3 -c "import json,sys; print(json.load(sys.stdin)['draft']['id'])")
   hypertask --json --token "$T" draft delete "$D" --project <board>
   ```

   A board with no tickets: print `write: no ticket to test`.

8. **One startup check.** Compare the live name and boards with what you set, then print one line:

   `identity: <your name>, boards <ids>, read ok, write ok`

   Nothing else, never the token. If `ship-identity` prints `Valentins Claude Code`, set `SHIP_SESSION_NAME="<your name>"` on writes or fix the session name.

## Assignment

Every ticket you file or work carries you as assignee.

- Filing: take it right after create: `hypertask agent take <ticket> --project <board>`.
- Starting work: the lease sync takes it for you when nobody is assigned to it (see `board.md`).
- Never assign a person, including Valentin.
- Never replace an existing assignee. Add yourself.

## Stop rules

- Never revoke, archive, rename or delete another chat's agent.
- Never copy a token from another machine or another agent.
- Never print a token, a key, or command output that holds one.
- A failed step blocks board work. Fix it and rerun the startup check.
