# ADD and CAREFUL let the launch through

A gate that blocks a healthy server is worse than no gate, because the chat learns to override it.

## Sub-features

- `verdicts.add`: exit 0 from `vps-state --can-launch worker` allows the call, exit 0 from the hook, nothing on stderr.
- `verdicts.careful`: exit 1 allows the call the same way. CAREFUL means start one job; the second call asks again.

## How to get to it (user POV)

- A chat on a healthy server notices nothing. The gate costs it one probe and no words.

## Driving it with run

- Action: the same incident launch, with a fake that exits 0, then one that exits 1.
- Evidence: `add.code`, `add.err`, `careful.code`, `careful.err`.
- Check: `verdicts` wants exit 0 from the hook both times and empty stderr.

## Gotchas

- Silence is part of the check. A warning printed on every allowed launch would train chats to ignore the one warning that matters.
