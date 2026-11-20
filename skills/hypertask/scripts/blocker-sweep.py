#!/usr/bin/env python3
"""Read-only. Lists blocked tickets that drifted on the given boards.

usage: blocker-sweep.py <boardId> [<boardId> ...] [--owner "Valentin Yeo"]

Prints one line per blocked ticket:
  ANSWERED     the owner replied or reacted after the marked comment: clear it now
  STALE        the work moved on (a merged PR, or the ticket sits in a done column): clear it
  NO-QUESTION  the marked comment has no "Question:": clear it or post one
  WAITING      a real open question: leave it
"""
import json, re, subprocess, sys

DONE_FALLBACK = {"Done", "No Flag", "Flag: Everyone", "Flag: Only Me + QA"}


def cli(*a):
    r = subprocess.run(["hypertask", *a, "--json"], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {}


def text(s):
    return re.sub(r"<[^>]+>", " ", s or "").strip()


def by_owner(c, owner):
    return not c.get("agent") and (c.get("creator") or {}).get("displayName") == owner


def classify(answered, stale, question):
    if answered:
        return "ANSWERED"
    if stale:
        return "STALE"
    if not question:
        return "NO-QUESTION"
    return "WAITING"


def done_sections(board):
    rows = cli("sections", "list", "--project", str(board)).get("sections") or []
    names = {r.get("section_title") for r in rows if r.get("isDone") is True}
    return names or DONE_FALLBACK


def merged_since(task, when):
    for pr in task.get("pullRequests") or []:
        state = pr.get("lifecycle") or pr.get("displayState")
        if state == "merged" and (pr.get("updatedAt") or "") > when:
            return pr.get("url") or f"PR {pr.get('number')} merged"
    return ""


def stale_reason(board, task, question, done):
    if task.get("section") in done:
        return f"ticket sits in {task.get('section')}"
    got = cli("task", "get", task["ticketNumber"], "--project", str(board)).get("tasks") or [{}]
    return merged_since(got[0], question.get("createdAt", ""))


def main(argv):
    owner = "Valentin Yeo"
    if "--owner" in argv:
        i = argv.index("--owner")
        owner = argv[i + 1]
        del argv[i:i + 2]
    if not argv:
        sys.exit(__doc__)

    counts = {"ANSWERED": 0, "STALE": 0, "NO-QUESTION": 0, "WAITING": 0}
    for board in argv:
        done = done_sections(board)
        tasks, offset = [], 0
        while True:
            page = cli("task", "list", "--project", board, "--limit", "200", "--offset", str(offset)).get("tasks", [])
            tasks += page
            if not page:
                break
            offset += len(page)
        for t in tasks:
            marked = t.get("blockerCommentId")
            if not marked:
                if t.get("section") == "Valentin Review":
                    counts["NO-QUESTION"] += 1
                    print(f"NO-QUESTION\t{t['ticketNumber']}\t{t.get('id')}\tno blocker comment\t{t.get('title', '')[:60]}\tin Valentin Review without a marked Question")
                continue
            cs = cli("comments", "list", t["ticketNumber"])
            cs = sorted(cs.get("comments", []) if isinstance(cs, dict) else cs, key=lambda c: c.get("createdAt", ""))
            q = next((c for c in cs if c.get("id") == marked), {})
            after = [c for c in cs if c.get("createdAt", "") > q.get("createdAt", "") and by_owner(c, owner)]
            reacted = any((r.get("user") or {}).get("displayName") == owner for r in q.get("reactions") or [])
            stale = "" if after or reacted else stale_reason(board, t, q, done)
            kind = classify(bool(after) or reacted, stale, "Question:" in text(q.get("text")))
            counts[kind] += 1
            reply = text(after[-1]["text"])[:120] if after else ("reacted" if reacted else stale)
            print(f"{kind}\t{t['ticketNumber']}\t{t.get('id')}\tcomment {marked}\t{t.get('title', '')[:60]}\t{reply}")
    print(" ".join(f"{k}={v}" for k, v in counts.items()), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
