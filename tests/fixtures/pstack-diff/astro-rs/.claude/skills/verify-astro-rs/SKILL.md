---
name: verify-astro-rs
description: Prove the rebuilt hypertask.ai at https://hypertask.ai/ratstack/ looks, reads and behaves like the old live https://hypertask.ai, with screenshots of old and new side by side, a visible text diff, a link and image diff, response status and head tags. Use after a merge to site, before claiming a page, link, image, head tag or layout matches, or when asked to verify the marketing site.
---

# Verify hypertask.ai

This skill drives the two live hosts the way a visitor does and keeps the evidence that says whether they match. It reads only: GET on both hosts, no login, no form, no chat message, no deploy.

The map is `features/README.md`, one file per top feature. The driver is `verify/driver.mjs`. This skill adds no second driver and no second map.

## Launch

There is nothing to build and nothing to start on this server. The instance under test is the preview that GitHub publishes on every merge to `site`:

- workflow `Publish hypertask.ai/ratstack` in `.github/workflows/publish-ratstack.yml`, on push to `site`, job `publish`
- the published address is `https://hypertask.ai/ratstack/`
- the reference is the old live site at `https://hypertask.ai/`

No dev server, no port, no seed data, no migration, no teardown. A page only counts once the publish run for the commit you mean has finished and passed.

The Chromium is already on this machine, under `~/.cache/ms-playwright`. Playwright must resolve from `verify/node_modules`. On the VPS the link is one command and it is gitignored:

```sh
ln -sfn /home/valentin/.npm-global/lib/node_modules verify/node_modules
```

The Verifier workflow links its own Playwright at the same path, so the driver is the same in both places.

## Doctor

Run this first, before any drive. It is read-only and it exits `0` only when the preview is worth driving.

```sh
node .claude/skills/verify-astro-rs/scripts/doctor.mjs
```

It prints one line per check, then the JSON:

- the reference host answers `200` with the live title `The fastest project board — Hypertask`
- the preview host answers
- the preview carries `noindex`, in an `X-Robots-Tag` header or a `robots` meta
- the preview serves its own build, so its scripts and styles answer under `/ratstack/assets/` and the first one it names answers `200`
- the last successful `publish-ratstack.yml` run on `site` is at the current `site` tip, so the preview is the build you think it is

A failed doctor is a failed run. Record which check failed and stop, unless the failure is only "the preview is not published yet": then still run the one mapped feature, because the visible difference is the proof that it is missing.

The run cannot pass while a preview check fails, even when the two sides look identical. Until the publish lands, `https://hypertask.ai/ratstack/` answers with the old site's home page, so an empty text diff there proves nothing: the verdict is FAIL, with the doctor's failed check as the reason.

## Drive

Both hosts take the same command and the same selector. Desktop is 1440 by 900, phone is 390 by 844.

```sh
export PREVIEW=https://hypertask.ai/ratstack
export REFERENCE=https://hypertask.ai
export RUN="$EVIDENCE_ROOT/<stamp>"

SCREENS_DIR="$RUN" node verify/driver.mjs page --head "$PREVIEW" --base "$REFERENCE" --path /
SCREENS_DIR="$RUN" node verify/driver.mjs compare --head "$PREVIEW" --base "$REFERENCE" --path /
SCREENS_DIR="$RUN" node verify/driver.mjs act --head "$PREVIEW" --base "$REFERENCE" --path / --click 'role=button[name="Pay monthly"]'
SCREENS_DIR="$RUN" node verify/driver.mjs act --head "$PREVIEW" --base "$REFERENCE" --path / --viewport 390 --press l
SCREENS_DIR="$RUN" node verify/driver.mjs probe --head https://hypertask.ai/ratstack --path /pricing
```

- `page` opens each path at 1440 and at 390, records status, head tags, headings, links, images, fonts, visible text, console errors, page errors and failed requests, screenshots each side, and writes `side-by-side.html` with the old capture beside the new one.
- `compare` diffs the visible text, the link list and the image list at 1440 and records both sides' status and head tags.
- `act` clicks one selector or presses one key on both sides, then records the resulting status, address, text, clipboard, head tags and screenshot. `--viewport 390` drives the phone layout.
- `probe` fetches without following a redirect, for an old address, a trailing slash or an unknown address.

The preview lives under `/ratstack` and the old site does not, so `compare` takes the head base path from `--head` (override with `--head-base-path`) and strips it before comparing. Two extra lists judge the move itself: `linksOutsideHeadBase` and `imagesOutsideHeadBase` name every link and image on the preview that still points at the site root, which is a link that leaves the preview and lands on the old site. Both must be empty.

Stable handles, shared by the old site and the rebuilt one:

- `#main-header`, `#main-content`, `#login-button`, `#mobile-menu`, `#cookie-consent`, `#get-started-button`
- `button[aria-label="Toggle menu"]`, `[aria-label="Footer"]`, `#main-header [role="group"][aria-label="Billing period"]`
- `role=tab[name="MCP"]`, `role=tab[name="CLI · Mac, Linux"]`, `role=tab[name="CLI · Windows"]`
- `role=button[name="Copy"]`, `role=button[name="Pay monthly"]`, `role=button[name="Pay yearly"]`, `role=button[name="Accept"]`, `role=button[name="Reject"]`

Reach for roles, accessible names and ids in that order. Never coordinates. Work from `features/README.md` and the feature file for the claim you are judging; driving one mapped feature is enough for a proof, and every entry point in the map is a separate claim.

One oddity of the header: the login button reads `Login` and its tooltip reads `Press L to log in` as three text nodes, so the visible text file carries `Press`, `L` and `to log in` on three lines. Judge the login link by its address in the link list, not by the tooltip sentence.

## Evidence

Every run writes into one folder outside the clone, and cleanup never deletes it:

```sh
export EVIDENCE_ROOT="${VERIFY_EVIDENCE_ROOT:-$HOME/.local/state/verify-astro-rs}"
export RUN="$EVIDENCE_ROOT/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$RUN"
node .claude/skills/verify-astro-rs/scripts/doctor.mjs | tee "$RUN/doctor.txt"
```

The folder holds `doctor.txt`, `report-page.json`, `report-compare.json`, `report-act.json`, `side-by-side.html`, one screenshot per side per viewport, the paired full-page screenshots, one visible-text file per side for every command, and the action screenshots. The run is proof only when all of these hold:

- the doctor passed, or its one failure is recorded as the reason the run fails
- both sides answered, and the status is recorded, not assumed
- the head tags of both sides are recorded: title, description, canonical, robots. `robots` differs on purpose: the preview says `noindex, follow` and the old site says `index, follow`. Everything else is equal, and `canonical` keeps the public address `https://hypertask.ai/...`, never `/ratstack/...`
- the action and the resulting state are both captured, not only the final screen. For the copy button that means the label after the click and the clipboard text, which the driver records
- the visible text diff, the link list diff and the image list diff are empty for the feature's pages, or every line in them is explained by the step that owns it
- `linksOutsideHeadBase` and `imagesOutsideHeadBase` are empty, so nothing on the preview still points at the site root
- the paired screenshots at 1440 and at 390 look the same, judged by eye, not by a diff count

A page missing from both sides is a note for the step that owns it. A page that works on the reference and is missing or different on the preview fails the run. Never weaken a journey to make it pass.

The pull request that hands this skill over keeps that run's `transcript.md` and two paired screenshots under `evidence/<stamp>/`; every later run writes only to `EVIDENCE_ROOT`.

## Cleanup

The driver closes the Chromium it launched in a `finally` block, and each context it opened for a journey. There is no server, no port and no process to stop.

- Never kill a browser by process name.
- Never delete the evidence folder. It is the proof.
- If a run dies before it closes, the next run starts its own browser; do not reuse or adopt a stray one.

## Helpers

- `node .claude/skills/verify-astro-rs/scripts/doctor.mjs` is executable, read-only, exits `0` when the preview is worth driving.
- `node verify/driver.mjs <page|compare|act|probe>` is executable and prints its own usage with `node verify/driver.mjs help`.
- `REFERENCE_URL`, `PREVIEW_URL`, `PREVIEW_BASE_PATH`, `VERIFY_REPO`, `PUBLISH_WORKFLOW` and `PUBLISH_BRANCH` override the doctor's defaults.
- `EVIDENCE_ROOT` and `SCREENS_DIR` name the evidence folder; `VERIFY_EVIDENCE_ROOT` moves the default root.
- `--head-base-path` overrides the path the preview is served under when `--head` does not carry it.
