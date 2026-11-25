# Views and labels

## Your own view

Own a view named exactly like your Multibot chat, or like the repo when the repo has one chat. Its filter is one label with the same name.

- One name everywhere: the view title, the label, your agent name and your session title are the same string (see `identity.md`).
- Create it when it is missing:

  ```bash
  hypertask view create --project <board id> --title "<your name>" --label "<your name>"
  ```

- List views: `hypertask view list --project <board id>`.
- Work from your view, not from the whole board.

## The board line

Each repo's project notes carry one line:

```
Hypertask board: <board id>
```

A repo with one chat may add the label as an override:

```
Hypertask board: <board id>, label: <label>
```

- The board is per repo.
- The label is per chat: when the line has no `label`, the hook, the lease and the checkup take it from the chat's resolved Multibot name.
- A chat with no resolved name gets no sync. That is a setup gap, not a reason to borrow a name.
- A label on the line wins over the chat name. Use it only for a one-chat repo.

## Label every ticket you touch

A ticket you file or work carries your label, so your view shows it.

- `task create --labels "<your name>,brain-medium"`
- `hypertask task update <ticket> --labels ...` only adds or replaces the labels you name; keep the others.
- A ticket of yours found on another view gets your label.
- The label you armed with owns your cards even when it classifies work too: a `--label Triage` loop owns its Triage cards, and no `no-owner-label` break fires on them.
- A ticket another chat owns moves to that chat's label. Tell that chat.

Never invent a label for a person, and never use Valentin's name as a label.
