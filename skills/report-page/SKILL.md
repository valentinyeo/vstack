---
name: report-page
description: Turn research, a plan, an analysis or a status update into one clean HTML page a busy person can scan in a minute. Writes with web-writing, cleans with unslop and zinsser-english-style, builds from the bundled template, then publishes. Use for /report-page, any report, research write-up, plan, comparison, audit or findings page meant for a person to read.
---

# report-page

One job: put findings on a page a tired reader understands in a minute. The page is built HTML, never markdown shown in a viewer.

## Steps

1. **Find the answer.** Write the one-sentence verdict before anything else. If you can't, the research isn't done.
2. **Pick what goes on the page.** At most 3 top items get a card. Everything else goes in one short table or is left out. Method and evidence go last.
3. **Write with `web-writing`.** Conclusion first, about half the words of a normal draft, one idea per paragraph, bold keywords, plain headings, no hype.
4. **Clean with `unslop`** (if installed), then **`zinsser-english-style`.** Cut AI phrasing, clutter and stale phrases. Short sentences, active verbs, concrete words. Use `schneider-deutsch-stil` instead for a German page.
5. **Build from `template.html`** in this folder. Keep its structure:
   - Verdict box at the top: the answer in bold, then at most one sentence and the next step.
   - Cards for the top items: a title, one proof line with the key number and a source link, and images inline when they help.
   - A warning box only when something must be fixed or watched.
   - A short table for the rest.
   - Method last, in two or three sentences.
6. **Images inline.** Shrink to about 640px wide JPEG, then embed as base64 so the page is one file. Look at every image yourself before it goes on the page.
7. **Publish.** Upload the single HTML file to your host, then open it and check: it loads, images show, it reads well at phone width, dark mode works.

## Rules

- **The page answers a question.** The first screen tells the reader what to do or believe. No intro, no "this report covers".
- **Evidence is a link, not a paragraph.** One number plus a source link beats three sentences of caveats. Keep caveats that change the decision; cut the rest.
- **No internal notes for the writer.** Leave out quota counts, file paths, tool names, "nothing was posted" disclaimers and process logs unless the reader needs them to act.
- **Links are full URLs** on the visible text that names the thing ("See it", the video title, the ticket title), never bare ids.
- **No em dashes, no emoji headings, sentence case headings.**
- **No secrets, tokens or private customer data** on the page.
- **Phone first:** 16px side margins, no sideways scrolling, tables hide minor columns on small screens (`class="hide-mobile"`).

## Final check

- Does the verdict box alone tell the reader what to do?
- Could you cut another 20% without losing a decision?
- Does reading only headings, bold words and first lines still give the whole story?
- Is every number sourced and every link working?
