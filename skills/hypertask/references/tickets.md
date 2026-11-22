# Tickets and comments

## What to file a ticket for

File one ticket for every unit of work before it starts:

- a branch, PR, worktree or running worker
- a bug, a missing capability, or a request that arrived in chat
- a correction to this repo's own rules, scripts or gates, on the repo's board and view

Do not file for an answer, a question, or a status update. Those go in chat or in a comment on the ticket that already exists.

A shared house-rules or pstack setup fault goes to board 2060, label Poteto. A Hypertask fault goes through `hypertask feedback` (see `cli.md`), never a ticket you write by hand. One topic, one ticket: search before you file.

## Parts

- **Title:** the change a user sees. No code words.
- **Problem:** 2 to 4 short bullets. Quote Valentin in a quote block (`> `) when he asked.
- **Fix:** what we do, in plain words.
- **Done when:** checks anyone can confirm. Every line names its proof.
- **Risk:** the worst case, plus the undo.
- **Decision:** one marked Question, or `none`.
- **Now** (top line while he must act): the state today plus his one call. Rewrite it when the state changes.
- **Result** (when done): what happened, 3 to 4 bullets.

One problem per ticket. Two bugs that can be fixed apart are two tickets, linked under "Not in this ticket". Every noun is something he can see: name the app and the screen.

## Brain tag

Every ticket carries exactly one `brain-*` label:

- `brain-light`: tiny fix, rename, one file, obvious one-liner.
- `brain-medium`: the default. Normal feature, bug, design apply.
- `brain-hard`: hard bug, security, money or billing, many systems.
- `brain-extra-hard`: rare. Auth or account integrity, or security plus money. Runners skip it.

Unsure: `brain-medium`. Keep every other label and replace only the `brain-*` one. The triage check is `skills/hypertask-triage/scripts/flow-check --board <id>`; it prints the NO-BRAIN count.

## Two lanes

**Human lane:** a title, a description, or a comment with `--kind question|qa|done`, and any comment that @mentions a person.

- Run `pospeak` on it first.
- Max 8 words per sentence. The guard bounces over 12.
- Answer first, in product-owner words.
- No file paths, function names, logs or transcript paths.
- Links are full clickable URLs.
- A person is notified only by real mention markup, never a plain name.

Mention markup, until the CLI has a flag (https://app.hypertask.ai/detail/project-15/8268):

```html
<span data-type="mention" class="mention" data-id="Full Name" data-label="name-<userId>" data-mention-suggestion-char="@">Full Name</span>
```

Get `<userId>` from `creatorId` in `hypertask comment list <ticket>`, or from an existing mention. Read the comment back: `name-<userId>` must be there.

**Agent lane:** `hypertask activity add <ticket> --text`, or a plain comment with no `--kind` and no mention, from an agent login. Claims, `Next:`, `Branch/PR:`, `Outputs:`, resume commands, paths, logs and evidence go here. Verbose is fine. Never post an agent note under a person's login.

## Comment rules that break rendering or notifications

- Wrap every description and comment in HTML block tags: `<p>`, `<ul><li>`, `<strong>`. Never bare text or a run of `<br>`.
- The first `<p>` is the bolded lede: what this comment is.
- One idea per `<p>`. Two or more items are a `<ul>`, never `1) 2) 3)` inside a paragraph.
- Ticket links are `<a href="https://app.hypertask.ai/detail/project-<board>/<n>">TEXT</a>` with the full URL visible. Never a bare key.
- Attach files with `--attach`. Never embed an image or a markdown image.
- Fix a wrong comment with `hypertask comment update <id> --text`. Never delete and repost. Never repeat an unchanged status.
- Evidence over prose: every claim carries a link (commit, report page, public screenshot). Never a server path.
- Never create or archive a ticket, or mention a person, unless the owner asked for it or this skill names it as a step. Never touch a ticket in Done.

## A Question

One open Question per ticket, marked as the blocker. Retire older ones.

```
What this is: <4 to 8 short pospeak lines>
Question: **<yes/no question?>**
My recommendation: Yes|No.
Why: <one line>.
Yes: <what happens>
No: <what happens>
```

- The recommendation sits right under the question.
- A blank line between lines, because single line breaks merge.
- "What this is:" comes first and says what the thing is in the app, why it reached him, and what Yes and No change.
- Only Chief Of Staff and the board's lead write a Question, or make Valentin the waiting person. A runner sets the waiting person to its lead, then to Chief Of Staff after 2 hours without a live lead.
- Money asks name the amount. Ask only when his answer can act today.
- His 👍 on the Question accepts the recommendation. Act on it, then clear both the waiting person and the red comment border.
- Before asking, check `skills/unblock/learned.md`. If the case is listed, decide it yourself.
- Never ask him for a rule exception, a test place or a tool permission.

## Done comment

Bold outcome first. Proof in one line. "Nothing to decide." The change link.

## Filing from one line

`/hypertask <text>`: the text describes a bug or a feature, optionally with screenshot or screencast URLs.

1. Pull out every `http(s)` image, PDF or screencast URL. Each one becomes `--attach <url>`.
2. `hypertask task search "<key words>"`. If a ticket already covers it, onboard that one instead.
3. Create it on the project's board:

   ```bash
   hypertask task create --project <id> --title "<title>" \
     --description-file <file> --labels "brain-medium" [--attach <url> ...]
   ```

4. Take it: `hypertask agent take <ticket> --project <id>`.
5. Continue as onboarding below.

## Onboarding a ticket by id

`/hypertask VSTA-33`, or any `PREFIX-NNN` or `app.hypertask.ai/detail/project-<id>/<n>` URL.

1. `hypertask task get <PREFIX-NNN>`. A URL only: find the prefix with `hypertask task list --project <id> --limit 5`.
2. `hypertask comment list <PREFIX-NNN>` and `hypertask task agent-log <PREFIX-NNN>`: read the whole ticket.
3. Move it to its working column (see `board.md`) and take it if you are not the assignee.
4. Post this session's resume string once, to the ticket's agent log:

   ```bash
   hypertask activity add <PREFIX-NNN> --text "<p><code>claude --resume $CLAUDE_CODE_SESSION_ID</code></p>"
   ```

5. Print the ready-to-paste `/rename` line: `/rename PREFIX-NNN | <Full Title>`.
6. Start the work. Do not wait for a go.

Reply with the full ticket URL. Runners put it in a ticket comment; only HT Product Lead opens a page in Valentin's browser, and only when mentioning it to him.

## Before posting

Reread the human-lane text once. A sentence over 8 words, or with a path? Rewrite it. Replace dev words with what he sees.

The guard checks human-lane text before it posts:

```bash
scripts/ticket-lint <file>
```

Pass `--old <file>` on an edit so only new lines are checked. Your own board-drain check reports answered waits; read waiting tickets on each tick and clear marks when the work moves. No wrapper? Run `ticket-lint` by hand before any raw `hypertask` write.
