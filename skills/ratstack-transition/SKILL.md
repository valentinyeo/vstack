---
name: ratstack-transition
description: Plan a forced rewrite of an existing app onto Rat Stack (github.com/joelhooks/rat-stack), as close to Joel Hooks' stack as possible. Pins Rat Stack at one commit, diffs the app against it, maps every behaviour onto Rat Stack's own nouns and layout, and files one ticket per slice. Use for /ratstack-transition, "move this app to Rat Stack", "rewrite on ratstack", or a stack review that says move. Any session or runner, any harness.
disable-model-invocation: true
skill-word-budget: 2000
skill-word-budget-reason: The rat-stack migration protocol must stay together.
---

# /ratstack-transition [app dir]

Prior art: pstack `poteto-mode` — checked shipping playbooks; no rat-stack migration skill there. Body copied from retired house-rules `skills/ratstack-transition`, with vstack paths for `/hypertask` and `scripts/rat-diff`.

Valentin, 2026-11-13:

> make a plan to FORCE an existing app
> to be rewritten with the exact plan of ratstack
> the point is to stick as close to his stack as possible

> anything that doesn't play well with ratstack is no bueno

Output: a rewrite plan on the app's board, one ticket per slice. This skill writes no app code. Runners build the tickets.

The one rule: **Rat Stack's own files decide.** Its AGENTS.md is law. Its pins are exact. Its layout, nouns and skills are the plan. When this skill and Rat Stack disagree, Rat Stack wins. Never invent a pattern Rat Stack has not got.

## 1. Pin Rat Stack

- Clone it next to the app: `gh repo clone joelhooks/rat-stack /tmp/rat-stack-<app>`.
- Record the commit: `SHA=$(git -C /tmp/rat-stack-<app> rev-parse HEAD)`. Every ticket names this commit, and so does every rat-diff run.
- Read in full, in this order: AGENTS.md, VISION.md, README.md, skills/rat-stack-mode/SKILL.md, skills/learn-rat-stack/SKILL.md, skills/keep-or-cut/SKILL.md.
- Skim every other `skills/*/SKILL.md`. Each slice ticket points at the Rat Stack skill that builds it (`add-a-capability`, `add-a-store`, `add-a-lifecycle-machine`, `add-a-feature-flag`, `ship`, `learn-alchemy`).

## 2. Diff the app

```
skills/ratstack-transition/scripts/rat-diff <app dir> --sha $SHA --rat /tmp/rat-stack-<app> --json /tmp/rat-diff-<app>.json
```

`--sha` pins the cloned commit, so the pin cannot drift. `--rat` reads the clone, not `gh api`. It prints, against that commit:
- **BUMP**: shared packages at another version. Take Rat Stack's exact pin.
- **DROP**: packages Rat Stack does not use, each with its replacement. `NO HOME` means cut it or port it by hand onto Effect. Never keep it.
- **ADD core**: packages every Rat Stack app has. All of them.
- **ADD by cartridge**: take only with the cartridge that needs them.
- **LAYOUT missing**: Rat Stack files and folders the app lacks.
- **FOREIGN files**: configs for tools Rat Stack does not use (wrangler, biome, npm lockfile, raw .env).
- **NON-JS manifests**: go.mod, Cargo.toml, pyproject.toml and the like.
- **LOOSE non-JS files**: .py, .go, .sh and other scripts with no manifest.
- **CDN tags**: script and link tags to Tailwind, Chart.js, React, htmx, fonts and the like. They are not in package.json, so DROP misses them.
- **SELF-HOSTED CI**: workflow lines with `runs-on: self-hosted`.
- **PAGES markers**: `pages_build_output_dir`, _routes.json, functions/, `wrangler pages`.

The script cannot see everything. Still read the code for inline `fetch` to outside APIs, server-rendered HTML and anything the sections miss.

## 3. Inventory what the app does

The rewrite must keep every behaviour. List each one from the code, not from docs:
- HTTP routes and API endpoints, with method and auth. Include form posts and HTML fragment endpoints.
- MCP tools, CLI commands, webhooks.
- Scheduled jobs (cron triggers), queues, Durable Objects.
- Storage: D1 tables and the migrations already applied, KV namespaces, R2 buckets, external databases. Names only.
- Secrets and settings: names only, never values.
- Screens and pages users see.
- Outside APIs it calls, CDN assets included.
- Helper scripts, extra CI workflows, project law and agent files (CLAUDE.md, AGENTS.md, skills).
- Tests that exist today. Each becomes a behaviour test.

Number every item. The coverage rule in step 6 uses the numbers.

## 4. Map every item onto a Rat Stack noun

Use the noun table in Rat Stack's AGENTS.md. Typical homes:

| App has | Rat Stack home |
|---|---|
| Route, endpoint, webhook | Contract in packages/core/src/contracts.ts + Capability via `implement`, projected with `toHttpApi` |
| Form post, HTML fragment endpoint | A Foldkit Message + Command that calls the same Capability over RPC. No separate form endpoint |
| MCP tool, CLI command | Same Capability, projected with `toToolkit` or `toCommand`; served by apps/cli |
| Retry, polling, multi-step job, status-field lifecycle | XState Machine in `packages/core/src/<name>-machine.ts` |
| Cron trigger, queue | A scheduled handler in an app-named Worker. See the Worker rule below |
| D1, Postgres | packages/database cartridge (D1 or Hyperdrive Postgres) |
| Login, users the app owns | packages/auth cartridge (Better Auth) |
| Cloudflare Access login | Access stays in front. A small Effect cartridge reads the JWT. See the Access rule below |
| Feature switch | packages/flags cartridge |
| Analytics events | packages/events cartridge |
| Screen or page | Foldkit Feature in `apps/web/src/features/<name>/` + Client in `apps/web/src/client/<name>/`, styled with StyleX |
| The app's look | Keep the app's own theme: its colours, fonts, sizes and corners, rebuilt in StyleX. Never copy Rat Stack's or Foldkit's look. docs.hypertask.ai and ai-chatbot keep their own themes |
| Charts | SVG drawn in Foldkit views. No chart library |
| CDN script or link tag | Same home as the package it loads (Tailwind to StyleX, fonts self-hosted). Never keep a CDN tag |
| Secret, setting | .env.schema (varlock) |
| KV, R2, D1, domain | Alchemy resource in apps/infra/alchemy.run.ts |
| Outside API call | Effect `HttpClient` behind a Capability. No vendor SDK unless Rat Stack pins it |
| Validation | Effect `Schema` on the Contract |
| Small helper script (Python, shell, Go) | Port to Effect, or cut with `keep-or-cut`. Never a stop |

An item with no home: run Rat Stack's `keep-or-cut`. Cut it, or write on its ticket why it stays and how it is built on Effect.

Rules behind the table:
- **Non-JS.** Only a native app (Go, Rust, Zig or Kotlin as the main app) is out of scope. Stop and say so. A small helper script is port-to-Effect-or-cut.
- **Workers.** Read Rat Stack's AGENTS.md for where Workers live. apps/site is Joel's site Worker, not a home for the app's jobs. Follow the apps/site/src/worker.ts pattern in an app-named Worker declared in alchemy.run.ts. Write the reason on the ticket.
- **Access.** Keep Cloudflare Access (Zero Trust) in front. Read the JWT in a small Effect cartridge, with the written reason on the ticket. Use Better Auth only for apps that own their users.
- **D1 already migrated.** Baseline the existing `d1_migrations` rows in the database cartridge. Never re-run a migration. Never drop a table.

## 5. Shape of the rewrite

- Start from the template, never edit the old app in place.
- **Repo choice.** New repo from the template when hosting changes (Pages to Workers) or the layout differs a lot: `gh repo create <owner>/<app>-rs --template joelhooks/rat-stack --private`. Otherwise a rat/ folder in the same repo. State the choice and the reason on the parent ticket.
- **Pages to Workers is part of the move.** Rat Stack deploys Workers. A Pages app (any PAGES marker) gets the Rat Stack `Website` Worker (apps/web), which serves static files and server rendering. The Pages project stays untouched until the delete slice.
- Cut Rat Stack's demo parts the app does not need with `keep-or-cut`. Keep the fence, apps/infra, apps/web, packages/capability, packages/core and the cartridges the map uses.
- Keep the fence whole: pins, tsconfig.base.json, oxlint.config.ts, oxfmt.config.ts, lefthook.yml, the anti-slop rules, .github/workflows/ci.yml. Never loosen a rule to make old code pass.
- **CI.** Rat Stack's ci.yml replaces the app's own build and test workflows. Keep security scans (gitleaks, secret scans) with a written reason, on GitHub-hosted runners. Everything else goes. Self-hosted runners are forbidden. Tests and builds run in GitHub Actions only.
- Port slice by slice. The old app keeps serving until the new one matches it.
- Data stays put. Alchemy adopts the live D1, KV and R2 resources (see `learn-alchemy`). No copy, no delete.
- **Cutover.** Deploy with Alchemy onto the same domain.
- **Rollback.** Pages app: re-point the domain to the previous Pages deployment. Worker app: redeploy the old Worker version. The new Worker has Rat Stack's own `pnpm deploy:rollback`. Write all that applies on the cutover ticket.

## 6. File the plan

**Find the board.** Software Factory apps: board 2060, in the app's own view. List views with `hypertask view list --project 2060` and match the app name. Other apps: their own board (ai-chatbot: the Support board). Follow `/hypertask`, references/tickets.md.

**Order.** File the parent first. File the children next, each with `--parent-task`. Then edit the parent to add the child links.

**Parent.** "Move <app> to Rat Stack". Description: the pinned commit, the rat-diff counts, the repo choice with its reason, the full map table, the slice list with links.

**Slices, in this order:**
1. Scaffold: template, cut unused parts, fence green in GitHub CI. Measure the built Worker size.
2. Project law and agent files. Rat Stack's child-project checklist: rename the `@rat-stack` scope, `pnpm sources:fetch`, `pnpm git-snapshot`, .shitrat/public-allow.json, Alchemy profile. Then replace the Project law, Architecture and Boundaries sections of AGENTS.md, write VISION.md, port the app's agent files and skills.
3. apps/infra: adopt every live resource and secret name. Plan only, no deploy.
4. Database: schema port and migration baseline.
5. Auth or access, if the app has any.
6. One ticket per Contract group. A group is one route prefix or resource.
7. One ticket per Machine. A Machine is any retry, polling, multi-step or status-field lifecycle.
8. One ticket per screen group (Foldkit + StyleX).
9. Tooling scripts and CI.
10. Parity check: every inventory item proved on a preview deploy.
11. Cutover on the live domain, with the rollback written down.
12. Delete the old code and every DROP package.

Each slice ticket names: the Rat Stack commit, the Rat Stack skill to follow, the inventory item numbers it owns, and "Done when" with `pnpm check` and `pnpm test` green in GitHub CI.

**Links.** Link every slice to the slices it needs, in the same turn as filing: `hypertask task link <slice> <needed-slice> --type BlockedBy`. Scaffold, project law, apps/infra, database and auth block every later slice. Contract and Machine slices block the screen slices that use them. The picker skips a ticket whose blockers are open; an unlinked slice gets offered, and a runner burns a run to find the gap. (HYCI-343, 13 Nov: SOFT-2060 and SOFT-2061 parked on foundation slices nobody had linked.)

**Coverage rule.** Each inventory item has one owning slice. A test that spans slices is owned by the last slice it needs.

**Brain tags.** One per ticket. Medium is the default for every slice kind. Hard for money, auth, secrets and the live cutover.

## 7. Stops

- **Paid plan.** The scaffold slice measures the built Worker size. Ask Valentin only if it is over the free limit: one Question on the parent ticket. Other new paid items (Hyperdrive, extra plans) are money too.
- Deleting live data: Valentin's call. The plan never needs it.
- Keys come from `stack-key`. Alchemy logs in through its profile, never an env var in the repo.

## 8. Self-check before posting

- Every DROP line, CDN tag, loose script, self-hosted workflow and Pages marker has an owning slice.
- Every inventory item sits in exactly one slice.
- No ticket names a package, tool or pattern missing from the pinned Rat Stack commit, unless its ticket gives the written reason from step 4.
- Reply with the parent ticket link and the slice count.
