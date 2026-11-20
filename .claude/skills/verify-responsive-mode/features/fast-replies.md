# Fast replies

A side question typed mid-job gets its own answer inside 60 seconds, and two
questions get two replies.

## Sub-features

- `reply 1`: "what is 17 + 25?" sent at 25s is answered with 42 inside 60s.
- `reply 2`: "what is the capital of France?" sent at 40s is answered with Paris inside 60s.
- `separate`: the reply holding 42 does not also hold Paris, and the reverse.
  Two blocks of one message count as one reply, because the grader joins every text
  block that shares a message id.
- `--hard` adds "how many days are in a leap year?" at 100s and "what colour do you
  get mixing blue and yellow?" at 150s, as `reply 3` and `reply 4`.

## How to get to it (user POV)

Give a session in responsive mode a long job, then type a question before it ends.

## Driving it with drive.py

`plan.json` lists every message with its send second. `chat.jsonl` gets one
`{"sent": ..., "t": ...}` line per message and one `{"ev": ..., "t": ...}` line per
event, so a reply's latency is a subtraction.

## Gotchas

- A headless chat queues a mid-turn message and answers it at the next tool result.
  One foreground step over 60 seconds fails `reply 1`, which is the whole point.
- A reply that answers in words ("forty-two") fails. The grader looks for the digits.
