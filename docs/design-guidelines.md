# sethu design guidelines & review checklist

Principles every change is checked against, so the tool stays coherent as it grows.
These are distilled from real decisions, not aspirations. When a change conflicts
with one, either don't make it or update this doc deliberately.

---

## UX

- **Brand every message.** Every sethu message (result header, refusal, cd,
  interactive, error, menu, first-run) starts with the `|^=^|` icon, so it reads as
  sethu speaking. Helper: `_msg(text, on)`.
- **Colorblind-safe palette (Okabe-Ito), and keep it lean.** blue = success,
  red/vermillion = failure, amber = warning, teal = brand/`[mode]` tag, orange =
  `⚠trust`. No green/red pairing. Differentiate with **weight or separators, not
  new hues** — every added color costs scannability. If tempted to add a color,
  don't.
- **Color = sethu's *interpretation*; plain = *relayed* content.** Color the things
  sethu understands and gives meaning to (exit status, mode, warnings). Never
  recolor the command's own output — it's data sethu just carries. (But do append a
  trailing `\033[0m` when the output contains ANSI, so a colour the command left
  open doesn't bleed into the rest of the transcript — that's hygiene, not
  recoloring.)
- **Don't color routine messages.** Refusals and info (interactive, isn't-allowed,
  cd, state-builtin) are the branded icon + `·` separator + **plain body** — they're
  normal outcomes, not alarms. Reserve color for *status* (✓/✗ exit) and *genuine
  problems* (e.g. the garbled-output warning is amber). Coloring every routine
  refusal would be warning fatigue.
- **`>` is free/private, `>>` costs tokens.** The whole product is about keeping
  output out of the model's context. Make the token cost visible at the moment it's
  incurred; never hide it.
- **Refusals teach, and lead with the safest path.** Say *why* it was refused, then
  the safest way to make it work (drop the write flag, run parts separately) before
  the generic `--allow`. A refusal is a mini how-to, not a dead end. Where a
  read-only alternative exists, show it; where none does, `--allow` is the honest
  answer.
- **Degrade gracefully.** Unknown interactive/full-screen programs → a `--launch`
  hint, not garbled bytes or a hang. Every failure ends with an actionable next
  step.
- **Truthful feedback.** Only report success when something actually changed
  (`✔ added` / `already allowed` / `not in list`, not always `✔`).
- **Plain, natural language.** No em-dashes; commas/colons/parentheses instead.
  Concrete over jargon ("read-only mode won't run it automatically", not "isn't
  auto-allowed"). Concise; say each thing once.

## Correctness

- **Every feature and CLI argument has a test.** Tracked in the coverage table at
  the top of `tests/test_sethu.py`, enforced by `TestCoverageEnforcement` (fails if
  any arg is untested). Add a row + test for anything new.
- **Validate values, not just types.** A hand-edited config must never crash or
  misbehave: coerce list entries to strings, fall back an invalid mode, reject an
  empty prefix, fall back malformed numbers.
- **Fail safe on bad input.** Fall back to defaults; don't crash the hook (it runs
  on every prompt).
- **Don't trust stale state.** When correctness depends on the current value,
  re-read/re-run rather than reusing an earlier result.

## Security

- **Read-only is decided by FLAGS, not just program names.** Every entry in the
  `READONLY` set needs an explicit exec/write-flag policy (`fd -x`, `rg --pre`,
  `yq -i`, `git --ext-diff` were misses). Auditing the whole set is part of any
  change that touches it.
- **Allowlist stays injection-hardened.** An allowlisted command may only be
  followed by plain arguments — no unquoted pipe/redirect/`;`/`&&`/subshell/
  substitution. Allowing `ls` must never permit `ls; rm`.
- **Fail closed.** Refuse rather than run when a guarantee can't be met (socket
  perms not 0600 → refuse; `O_NOFOLLOW` on predictable temp paths).
- **Trust is opt-in, off by default, loud.** `--trust` removes the allowlist; it's
  warned and shown as `⚠trust` while active. Never widen what runs without an
  explicit user action.
- The runner executes in the user's shell **without** per-command permission
  prompts, so treat the allowlist like shell aliases: keep it tight.

## Performance

- **The `UserPromptSubmit` hook runs on EVERY prompt.** Keep the non-sethu fast path
  cheap: decide with `json`/`os` only and DON'T import `_engine` for a normal
  message. sethu's own overhead should stay sub-millisecond.
- **Measure before optimizing.** Interpreter startup dominates; most in-process work
  is already sub-microsecond. Don't add per-prompt work for a micro-optimization.

## Storage

- **Bound captured output** in RAM and on disk (a single `> yes` / `> cat big.iso`
  must not balloon memory or write a multi-GB temp file).
- **Every temp artifact sethu writes must be swept.** Anything under
  `sethu-*` (output logs, launch scripts, sockets, cwd files) is age-swept by
  `_sweep_temp`; a new artifact type must be added to it. Nothing grows unbounded.

---

## Checklist for any change

- [ ] **Tested** — a test added/adjusted; coverage-table row updated; `TestCoverageEnforcement` green; full suite passes.
- [ ] **UX** — branded (`|^=^|`), colorblind-safe & no new hue, truthful, actionable, plain language, no em-dashes.
- [ ] **Correctness** — validates input, fails safe, doesn't rely on stale state.
- [ ] **Security** — does it widen what runs? flags (not just names) audited? fails closed? trust still opt-in?
- [ ] **Performance** — no new work on the every-prompt path; fast path still skips `_engine`.
- [ ] **Storage** — output stays bounded; any new temp artifact is swept.
- [ ] `claude plugin validate .` passes.
