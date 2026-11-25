#!/usr/bin/env python3
"""Stop hook: a question for Valentin goes in the first paragraph of the reply, never below it.
He reads the top, and a question buried at the bottom stalls the work overnight.

One ask is allowed through: a product repo's own gate can demand a question, and the gate it
enforces in code wins inside that product. Hypertask's ht-flag refuses a flag switch without
Valentin's yes on `Switch <flag-key> to <mode>`, so that question never blocks.

ask-first-guard.py              hook mode, reads hook JSON on stdin
ask-first-guard.py --self-test
"""
import json
import re
import sys


def paragraphs(reply):
    text = re.sub(r"```.*?```", "", reply, flags=re.S)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\"[^\"\n]*\"|\u201c[^\u201d\n]*\u201d", "", text)
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(">"))
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def has_question(par):
    return bool(re.search(r"\?(?:\*\*|_|\))*\s*$", par, re.M))


# Hypertask's ht-flag refuses a switch without this question, so asking it is not a how-ask.
FLAG_KEY = r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*"
FLAG_MODE = r"off|owner\s*(?:\+|and)\s*qa|owner(?:\s+only)?|everyone|only[-_ ]me"
FLAG_SWITCH = re.compile(rf"\bswitch\s+{FLAG_KEY}\s+to\s+(?:{FLAG_MODE})\b", re.I)

HOW_ASK = re.compile(r"\b(?:should i|shall i|want me to|do you want me to|may i|should we|how should|which (?:one|approach|option) (?:should|do you)|would you like me to)\b", re.I)
HIS_CALL = re.compile(r"(?:money|spend|cost|price|pay|paid|subscription|budget|invoice|credits?|top up|billing|charge|\u00a3|\$\d|\u20ac|"
                      r"\bsend\b|email|message|post\b|tweet|publish|reply to|customer|client|"
                      r"deploy|force.push|"
                      r"pstack (?:can.?t|cannot|has no)|no pstack answer|exceptional|"
                      r"key|token|password|credential|secret|"
                      r"delet\w*|wipe|drop|destroy)", re.I)


def how_asks(reply):
    """Questions asking Valentin how or whether to do something that is not his call."""
    out = []
    for p in paragraphs(reply):
        if re.search(r"pstack (?:can.?t|cannot|has no)|no pstack answer|exceptional", p, re.I):
            continue
        for sent in re.findall(r"[^.!?\n]*\?", p):
            if HOW_ASK.search(sent) and not HIS_CALL.search(sent) and not FLAG_SWITCH.search(sent):
                out.append(sent.strip()[:100])
    return out


def buried(reply):
    pars = paragraphs(reply)
    if len(pars) < 2 or has_question(pars[0]):
        return []
    return [p.splitlines()[0][:100] for p in pars[1:] if has_question(p)]


def last_reply(tpath):
    with open(tpath, encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]

    def real_user(e):
        if e.get("type") != "user":
            return False
        c = (e.get("message") or {}).get("content")
        return isinstance(c, str) or (isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "text" for b in c))

    start = max((i for i, e in enumerate(lines) if real_user(e)), default=-1) + 1
    texts = []
    for e in lines[start:]:
        if e.get("type") == "assistant":
            for b in (e.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                    texts.append(b["text"])
    return texts[-1] if texts else ""


def self_test():
    assert not how_asks('**How you test it:** ask me any "how should we fix X?" question. My answer ends with a source line.'), 'a quoted example question is not an ask'
    cases = {
        "Should I delete it? Yes is my pick.\n\nDetails here.": 0,
        "Done. PR is up.\n\nDetails.\n\nShould I do it?": 1,
        "Done.\n\n**Merge it?**": 1,
        "Short answer with no question.\n\nMore detail.": 0,
        "One paragraph only. Want more?": 0,
        "Done.\n\n> is this how lauren would do it?\n\nShe would not.": 0,
        "Done.\n\nRun `ls foo?` then check https://x.com/a?b=1": 0,
    }
    how = {
        "Should I do all three now? I'd say yes.": 1,
        "Should I make both load by themselves when every session starts?": 1,
        "Should I set board 15 up like the table below?": 1,
        "Should I delete the plain key copies still on this server?": 0,
        "May I create a new Cloudflare key for this site?": 0,
        "Should I make the repo public? My pick: yes.": 1,
        "Done. What do you want help with?": 0,
        "Should I switch beta-banner to Off? My pick: yes.": 0,
        "Want me to switch payments_v2 to Everyone?": 0,
        "Should I switch invoice-export to Owner + QA, as ht-flag needs? My pick: yes.": 0,
        "Switch dark-mode-default to OWNER_AND_QA?": 0,
        "Should I switch the flag to Off? My pick: yes.": 1,
        "Should I use approach A or B? My pick: A.": 1,
    }
    ok = True
    for text, want in how.items():
        if bool(how_asks(text)) != bool(want):
            ok = False
            print(f"FAIL how-ask want {want}: {text!r}")
    for text, want in cases.items():
        got = len(buried(text))
        if (got > 0) != (want > 0):
            ok = False
            print(f"FAIL want {want} got {got}: {text!r}")
    print("ask-first-guard self-test ok" if ok else "ask-first-guard self-test FAILED")
    sys.exit(0 if ok else 1)


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    try:
        data = json.load(sys.stdin)
        if data.get("stop_hook_active"):
            sys.exit(0)
        reply = data.get("last_assistant_message") or (last_reply(data["transcript_path"]) if data.get("transcript_path") else "")
        bad = buried(reply)
        how = how_asks(reply)
    except Exception:
        sys.exit(0)
    if how:
        reason = (
            "Your reply asks Valentin how or whether to do something that is not his call:\n"
            + "\n".join(f"  - {h}" for h in how)
            + "\n\nHis calls are only money, rotating or deleting keys, and deleting live data, "
            "plus gates a product repo enforces in code, such as Hypertask flag switches "
            "(ask `Switch <flag-key> to <mode>?`). "
            "Everything else has a default: do it the way pstack and Lauren Tan would, then report what you did and why. "
            "Redo the reply: decide, act (or say you are acting), and drop the question."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(0)
    if not bad:
        sys.exit(0)
    reason = (
        "Your reply asks Valentin something below the first paragraph. He reads the top and stops, so the work stalls:\n"
        + "\n".join(f"  - {b}" for b in bad)
        + "\n\nRedo the same reply with the question as its first line, with your pick, "
        "for example: \"Question: delete the old skill? My pick: yes.\" Delete it from lower down, so it appears once. Everything else stays below it. "
        "If you can decide it yourself, decide, drop the question and report what you did."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


if __name__ == "__main__":
    main()
