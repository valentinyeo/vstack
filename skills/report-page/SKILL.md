---
name: report-page
description: Turn research, a plan, an analysis or a status update into one clean HTML page a busy person can scan in a minute. Bottom line up front, Minto pyramid structure, reading time shown. Writes with web-writing, cleans with unslop and zinsser-english-style, builds from the bundled template, then publishes. Use for /report-page, any report, research write-up, plan, comparison, audit or findings page meant for a person to read.
---

# report-page

One job: put findings on a page a tired reader understands in a minute. The page is built HTML, never markdown shown in a viewer.

## Save the reader's time: BLUF and the Minto pyramid

The reader should be able to stop after any layer and still have what they need. Structure every page as a pyramid (Barbara Minto, "The Pyramid Principle") with the bottom line up front (BLUF, the US military briefing rule).

1. **Bottom line (the top of the pyramid).** One sentence: the answer, verdict or recommendation. Then the one action you need from the reader, or "no action needed". This goes in the verdict box. A reader who stops here has the decision.
2. **Key points (the middle layer).** Two to four reasons that support the bottom line. They don't overlap and together they cover the case (Minto's MECE: mutually exclusive, collectively exhaustive). Each is one sentence and becomes a card or section heading. A reader who stops here knows why.
3. **Evidence (the base).** Numbers, sources, examples and method under each key point. Only the reader who doubts a point reads this layer.

Rules that follow from the pyramid:
- **Answer first, then reasons, then evidence.** Never build up to the conclusion.
- **Headings are statements, not topics.** "Claude Code videos get 17x normal views", not "Video demand".
- **Every item supports the layer above it.** Anything that doesn't is cut or moved to the method section.
- **If context is needed, keep it to SCQA in two lines max** (Situation, Complication, Question, Answer), placed after the bottom line, never before it.
- **Show the time cost.** Put the reading time next to the date ("2 min read", at about 200 words a minute), and keep most pages under 3 minutes.

## Steps

1. **Find the bottom line.** Write the one-sentence answer and the one action before anything else. If you can't, the research isn't done.
2. **Build the pyramid.** Pick the 2 to 4 key points that prove it. At most 3 top items get a card. Everything else goes in one short table or is left out. Method and evidence go last.
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

- Does the verdict box alone tell the reader what to do? (BLUF)
- Does each key point support the bottom line, without overlap? (Minto)
- Are the headings statements a reader could quote back?
- Is the reading time shown, and under 3 minutes?
- Could you cut another 20% without losing a decision?
- Does reading only headings, bold words and first lines still give the whole story?
- Is every number sourced and every link working?
