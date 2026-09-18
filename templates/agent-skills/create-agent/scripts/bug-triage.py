#!/usr/bin/env python3
"""Score and maintain one board's Bugs and Triage columns."""

import argparse
import datetime as dt
import html
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

PRIORITIES = ("Urgent", "High", "Medium", "Low")
PRIORITY_RANK = {value.casefold(): rank for rank, value in enumerate(PRIORITIES)}
CORE_WORDS = re.compile(
    r"\b(login|sign[ -]?in|sign[ -]?up|checkout|payment|billing|purchase|publish|save|"
    r"create|upload|download|board|task|ticket|invite|onboarding)\b",
    re.I,
)
BROKEN_WORDS = re.compile(
    r"\b(broken|blocked|cannot|can't|fails?|failure|crash(?:es|ed)?|outage|down|"
    r"unusable|stuck|missing|lost|error)\b",
    re.I,
)
MANY_USERS = re.compile(
    r"\b(all|every|many|multiple|several|team(?:s)?|customer(?:s)?|user(?:s)?|everyone|"
    r"company|companies|organisation(?:s)?|organization(?:s)?)\b",
    re.I,
)
ONE_USER = re.compile(r"\b(one|single|a user|a customer|me|my)\b", re.I)
NO_WORKAROUND = re.compile(r"\b(no|without) (?:known )?workaround\b|\bno alternative\b", re.I)
HAS_WORKAROUND = re.compile(r"\bworkaround(?: is|:)?\s+(?!none|no\b)|\bcan still\b|\binstead\b", re.I)
QUESTION = re.compile(r"\bQuestion\s*:", re.I)
HTML_TAG = re.compile(r"<[^>]+>")
TITLE_NOISE = re.compile(r"\b(?:bug|issue|error|broken|fails?|failure)\b", re.I)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", required=True)
    parser.add_argument("--input", required=True, help="board fixture JSON, or - for stdin")
    parser.add_argument("--state", required=True)
    parser.add_argument("--board-cli", required=True)
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--now", default="")
    parser.add_argument("--interval-seconds", type=int, default=14400)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_json(path, default):
    try:
        if path == "-":
            return json.load(sys.stdin)
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def parse_time(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        try:
            parsed = dt.datetime.combine(dt.date.fromisoformat(value), dt.time(), dt.timezone.utc)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def plain(value):
    return " ".join(html.unescape(HTML_TAG.sub(" ", str(value or ""))).split())


def labels_of(task):
    labels = []
    for label in task.get("labels") or []:
        if isinstance(label, dict):
            label = label.get("name") or label.get("title") or label.get("label") or ""
        if str(label).strip():
            labels.append(str(label).strip().casefold())
    return labels


def priority_of(task):
    priority = task.get("priority") or ""
    if isinstance(priority, dict):
        priority = priority.get("name") or priority.get("title") or ""
    value = str(priority).strip().title()
    return value if value in PRIORITIES else ""


def assignee_ids(task):
    found = set()
    for assignee in task.get("assignees") or []:
        if not isinstance(assignee, dict):
            continue
        for value in (assignee.get("id"), (assignee.get("user") or {}).get("id")):
            if value is not None and str(value):
                found.add(str(value))
    return found


def comment_text(comment):
    return plain(comment.get("text") or comment.get("commentText") or comment.get("html") or "")


def owner_id(document):
    project = document.get("project") or {}
    if isinstance(project.get("project"), dict):
        project = project["project"]
    owner = project.get("owner") if isinstance(project.get("owner"), dict) else {}
    value = project.get("ownerId") or owner.get("id") or ""
    return str(value)


def ticket_ref(task):
    return str(task.get("ticketNumber") or task.get("ref") or task.get("id") or "")


def ticket_url(board, task):
    given = str(task.get("url") or "")
    if given.startswith("https://"):
        return given
    ref = ticket_ref(task)
    suffix = ref.rsplit("-", 1)[-1] if "-" in ref else str(task.get("id") or "")
    return f"https://app.hypertask.ai/detail/project-{quote(str(board))}/{quote(suffix)}"


def explicit_triage(task):
    value = task.get("triage")
    return value if isinstance(value, dict) else {}


def score_task(task, now, previous_bot_priority, comments=()):
    title = plain(task.get("title"))
    description = plain(task.get("description"))
    detail = " ".join([description, *(comment_text(comment) for comment in comments)])
    text = f"{title} {detail}"
    explicit = explicit_triage(task)
    points = 0
    reasons = []

    users = explicit.get("usersAffected")
    if isinstance(users, (int, float)):
        user_points = 2 if users >= 2 else 1 if users > 0 else 0
    elif str(users).casefold() in {"many", "all", "multiple", "team", "teams"} or MANY_USERS.search(text):
        user_points = 2
    elif str(users).casefold() in {"one", "single"} or ONE_USER.search(text):
        user_points = 1
    else:
        user_points = 0
    points += user_points
    if user_points:
        reasons.append("multiple users" if user_points == 2 else "one user")

    core = explicit.get("coreFlowBroken")
    core_broken = core is True or (core is not False and CORE_WORDS.search(text) and BROKEN_WORDS.search(text))
    if core_broken:
        points += 2
        reasons.append("core flow broken")

    workaround = explicit.get("workaroundExists")
    if workaround is False or (workaround is None and NO_WORKAROUND.search(text)):
        points += 2
        reasons.append("no workaround")
    elif workaround is True or (workaround is None and HAS_WORKAROUND.search(text)):
        points -= 1
        reasons.append("workaround exists")

    created = parse_time(task.get("createdAt") or task.get("created_at"))
    age_days = max(0, (now - created).days) if created else 0
    if age_days >= 30:
        points += 2
        reasons.append(f"open {age_days} days")
    elif age_days >= 7:
        points += 1
        reasons.append(f"open {age_days} days")

    current = priority_of(task)
    owner_urgent = current == "Urgent" and previous_bot_priority != "Urgent"
    due = parse_time(task.get("dueDate") or task.get("due_date"))
    if owner_urgent:
        priority = "Urgent"
        reasons.insert(0, "owner marked Urgent")
    elif due:
        priority = "Urgent"
        reasons.insert(0, "due date")
    elif points >= 5:
        priority = "High"
    elif points >= 3:
        priority = "Medium"
    else:
        priority = "Low"

    enough_detail = len(detail) >= 40
    signals = user_points > 0 and (core is not None or bool(CORE_WORDS.search(text))) and (
        workaround is not None or bool(NO_WORKAROUND.search(text)) or bool(HAS_WORKAROUND.search(text))
    )
    unclear = not (enough_detail and signals)
    return {
        "priority": priority,
        "points": points,
        "reasons": reasons or ["limited impact reported"],
        "due": due,
        "created": created,
        "unclear": unclear,
    }


def duplicate_key(task):
    title = TITLE_NOISE.sub(" ", plain(task.get("title")).casefold())
    return " ".join(re.findall(r"[a-z0-9]+", title))


def has_agent_question(comments, agent_id):
    for comment in comments:
        agent = comment.get("agent") if isinstance(comment.get("agent"), dict) else {}
        if QUESTION.search(comment_text(comment)) and (not agent_id or str(agent.get("id") or "") == agent_id):
            return True
    return False


def run(cli, *arguments, dry_run=False):
    action = [cli, *arguments]
    print(json.dumps({"command": action[1:]}))
    if dry_run:
        return
    subprocess.run(action, check=True, stdout=subprocess.DEVNULL)


def comment(cli, ref, body, dry_run):
    run(cli, "comment", "add", ref, "--text", body, dry_run=dry_run)


def summary_html(board, ranked, movements, unclear):
    top = "; ".join(
        f'<a href="{ticket_url(board, row["task"])}">{html.escape(ticket_ref(row["task"]))}</a> {row["score"]["priority"]}'
        for row in ranked[:5]
    ) or "No open bugs"
    if movements:
        moved = "; ".join(
            f'{movement["ref"]} {movement["old"]} to {movement["priority"]} because {movement["reason"]}'
            for movement in movements[:3]
        )
        if len(movements) > 3:
            moved += f"; {len(movements) - 3} more rescored"
    else:
        moved = "No priorities moved"
    body = (
        f"<p><strong>Decision: Bug triage ranked {len(ranked)} tickets.</strong></p>"
        f"<p>Top five: {top}.</p><p>Moved: {html.escape(moved)}.</p>"
        "<p>Next: Work from this order until tomorrow's update.</p>"
    )
    if unclear:
        row = unclear[0]
        body += (
            f'<p>Question: Can you clarify impact and workaround on '
            f'<a href="{ticket_url(board, row["task"])}">{html.escape(ticket_ref(row["task"]))}</a>?</p>'
        )
    return body


def save_state(path, state):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


def main():
    args = parse_args()
    now = parse_time(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
    if now is None:
        raise SystemExit("--now must be an ISO date or timestamp")
    state = load_json(args.state, {})
    last_run = parse_time(state.get("last_run"))
    if last_run and (now - last_run).total_seconds() < args.interval_seconds:
        print(json.dumps({"skipped": "four-hour interval", "last_run": state["last_run"]}))
        return

    document = load_json(args.input, {})
    tasks = document.get("tasks") or []
    comments = document.get("comments") or {}
    owner = owner_id(document)
    protected = []
    standing = None
    candidates = []
    for position, task in enumerate(tasks):
        section = str(task.get("section") or "").strip().casefold()
        status = str(task.get("status") or "Normal").strip().casefold()
        if status not in {"normal", "open"}:
            continue
        if plain(task.get("title")).casefold() == "bug triage":
            standing = task
            continue
        if section not in {"bugs", "triage"}:
            continue
        if "valentin" in labels_of(task) or (owner and owner in assignee_ids(task)):
            protected.append(task)
            continue
        candidates.append((position, task))

    if standing is None:
        if not args.dry_run:
            state["last_run"] = now.isoformat().replace("+00:00", "Z")
            save_state(args.state, state)
        print(json.dumps({"skipped": "no standing Bug triage ticket", "board": args.board}))
        return

    previous_priorities = state.get("priorities") if isinstance(state.get("priorities"), dict) else {}
    asked = set(state.get("asked") or [])
    archived_duplicates = set(state.get("archived_duplicates") or [])
    scored = []
    for position, task in candidates:
        ref = ticket_ref(task)
        task_comments = comments.get(str(task.get("id"))) or comments.get(ref) or []
        scored.append({
            "position": position,
            "task": task,
            "score": score_task(task, now, previous_priorities.get(ref), task_comments),
        })

    duplicate_groups = {}
    for row in scored:
        key = duplicate_key(row["task"])
        if key:
            duplicate_groups.setdefault(key, []).append(row)
    duplicate_rows = set()
    for group in duplicate_groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda row: (row["score"]["created"] or now, row["position"]))
        older = group[0]
        for newer in group[1:]:
            newer_ref = ticket_ref(newer["task"])
            duplicate_rows.add(newer_ref)
            if newer_ref in archived_duplicates:
                continue
            older_ref = ticket_ref(older["task"])
            body = (
                f'<p><strong>Decision: This duplicates <a href="{ticket_url(args.board, older["task"])}">'
                f'{html.escape(older_ref)}</a>.</strong></p><p>The newer ticket is archived.</p>'
                "<p>Next: Follow the older ticket.</p>"
            )
            comment(args.board_cli, newer_ref, body, args.dry_run)
            run(args.board_cli, "task", "link", newer_ref, older_ref, "--type", "duplicate", dry_run=args.dry_run)
            run(args.board_cli, "task", "update", newer_ref, "--status", "Archive", dry_run=args.dry_run)
            archived_duplicates.add(newer_ref)

    active = [row for row in scored if ticket_ref(row["task"]) not in duplicate_rows]

    def rank_key(row):
        score = row["score"]
        due = score["due"]
        return (
            PRIORITY_RANK[score["priority"].casefold()],
            due.timestamp() if due else float("inf"),
            -score["points"],
            score["created"].timestamp() if score["created"] else float("inf"),
            row["position"],
        )

    ranked = sorted(active, key=rank_key)
    movements = []
    next_priorities = {}
    for row in ranked:
        task = row["task"]
        ref = ticket_ref(task)
        priority = row["score"]["priority"]
        old = priority_of(task)
        next_priorities[ref] = priority
        if old != priority:
            run(args.board_cli, "task", "update", ref, "--priority", priority, dry_run=args.dry_run)
            movements.append({
                "ref": ref,
                "old": old or "unranked",
                "priority": priority,
                "reason": row["score"]["reasons"][0],
            })

    unclear = []
    for row in ranked:
        task = row["task"]
        ref = ticket_ref(task)
        task_comments = comments.get(str(task.get("id"))) or comments.get(ref) or []
        if row["score"]["unclear"] and ref not in asked and not has_agent_question(task_comments, args.agent_id):
            body = (
                "<p><strong>Question: How many users are affected, which core flow breaks, "
                "and is there a workaround?</strong></p>"
            )
            comment(args.board_cli, ref, body, args.dry_run)
            asked.add(ref)
            unclear.append(row)

    pending = state.get("pending_movements") if isinstance(state.get("pending_movements"), list) else []
    movement_by_ref = {}
    for movement in pending + movements:
        if isinstance(movement, dict) and movement.get("ref"):
            movement_by_ref[movement["ref"]] = movement
    pending = list(movement_by_ref.values())
    today = now.date().isoformat()
    posted_summary = state.get("last_summary_date") != today
    if posted_summary:
        comment(
            args.board_cli,
            ticket_ref(standing),
            summary_html(args.board, ranked, pending, unclear),
            args.dry_run,
        )

    if not args.dry_run:
        state.update({
            "last_run": now.isoformat().replace("+00:00", "Z"),
            "last_summary_date": today if posted_summary else state.get("last_summary_date"),
            "priorities": next_priorities,
            "asked": sorted(asked),
            "archived_duplicates": sorted(archived_duplicates),
            "pending_movements": [] if posted_summary else pending,
        })
        save_state(args.state, state)
    print(json.dumps({
        "board": args.board,
        "ranked": [ticket_ref(row["task"]) for row in ranked],
        "protected": [ticket_ref(task) for task in protected],
        "duplicates": sorted(duplicate_rows),
    }))


if __name__ == "__main__":
    main()
