# Worker brief rules

Faults: Hypertask bug -> hypertask feedback; our rules or scripts -> board 2060 ticket with label Poteto.

Report faults before working around them.
For Hypertask faults, run this command:

```sh
hypertask feedback --kind bug|friction|missing --category <c> --tool "<command>" --status <http> --error-code <slug> "<note>"
```

Choose one kind and the matching category.
Use the observed status when available.
Omit status when no HTTP response exists.
Feedback files on board 15.
Never include task, board or comment content.
Report command metadata and a sanitized note.

Our rules, scripts or gates failed?
File a ticket on board 2060.
Add label Poteto.
Keep working after recording the fault.
These reporting rules override legacy workaround instructions.
