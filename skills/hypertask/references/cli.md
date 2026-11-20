# The hypertask CLI

`hypertask` is the native Zig CLI. MCP is off in Claude Code; the CLI replaces it.

## Reading the CLI

- `hypertask --help` lists commands.
- `hypertask <command> --help` lists that command's flags.
- `hypertask capabilities --json` is the complete command and option catalog.
- `hypertask --version` prints the version. This skill is written for 0.2.68.

Never guess a flag. Read `--help` first.

## Shapes that matter

- `--json` goes before the subcommand: `hypertask --json task get VSTA-33`.
- `--token <jwt>` also goes before the subcommand. In scripts, pass `HYPERTASKS_JWT_TOKEN` instead, so the token never lands in a command line or log.
- `task get` wants the ticket key (`VSTA-33`), not the bare number.
- `task list --limit` caps at 100. Page with `--offset`. Piped output is plain tab-separated text and is safe to parse.
- Comments are top-level: `hypertask comment add <ticket> --text "<html>"`, then `hypertask comment list <ticket>`. There is no `task comment`.
- `task create` rejects a multi-line `--description`. Use `--description-file <path>`, or create short and then `task update --description`.
- `--attach <path-or-url>` lives on `task create` and `comment add`, and repeats. Use it for screenshots, PDFs and screencasts. Never embed an image in the HTML.
- Archive: `hypertask task update <ticket> --status Archive`. Statuses are Normal, Archive and Deleted. Never use Deleted.
- Move inside a board: `hypertask task move <ticket> --section "<name>"`.
- Assign: `hypertask task assign <ticket> --assignee <id>` adds, and `--assignee ""` or `--clear-assignees` clears. `hypertask agent take <ticket>` assigns your agent.
- Moving a ticket to another board is broken (HTTP 404, https://app.hypertask.ai/detail/project-15/3199). Create a ticket on the target board, then archive the old one.
- `task agent-log <ticket>` reads the agent log. `activity add <ticket> --text` writes it.

## Tokens

Your token file is `~/.config/hypertask-agents/credentials/sessions/<slug>-agent-token`, mode 600 (see `identity.md`).

```bash
export HYPERTASKS_JWT_TOKEN=$(cat ~/.config/hypertask-agents/credentials/sessions/<slug>-agent-token)
hypertask --json context
```

## When a command fails

File feedback on the same minute, then keep working:

```sh
hypertask feedback --kind bug|friction|missing --category <category> \
  --tool "<the command>" --status <http status> --error-code <slug> "<one line>"
```

Categories: `call_failed`, `empty_result`, `unexpected_result`, `auth_failed`, `slow`, `user_reported_broken`, `other`.

- One kind and the matching category.
- Keep the HTTP status only when you saw one. Omit it when there was no response.
- Never include ticket, board or comment content. Command metadata and a sanitized note only.
- Feedback files on board 15. Put the feedback link on the ticket.

The CLI also sends command name and error type on an unexpected failure. Disable that with `HYPERTASK_NO_ERROR_REPORTS=1` only when a person asks.
