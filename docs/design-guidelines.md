# sethu design guidelines & review checklist

Principles every change is checked against, so the tool stays coherent as it grows.
These are distilled from real decisions, not aspirations. When a change conflicts
with one, either don't make it or update this doc deliberately.

---

## UX

- **Every response opens with `|^=^| · `** so people instantly recognize it as sethu
  (not their own shell or Claude). This holds for *all* output — bridged `>`/`>>`
  results, the `>>` local note, management (`sethu --…`) output, help, the first-run
  hint, and errors. The hook routes every user-facing emission through `_lead`, which
  prepends the icon + `·` separator (de-duped, never doubled), and
  `TestEveryResponseLeadsWithIcon` drives one of each kind end-to-end so a new path
  that drops it fails CI. Add a case there when you add a response kind.
- **One unified header for every response.** Result *and* message share
  `|^=^| · [mode] [⚠trust] · [status ·] $ cmd` (helper `_header`), every part dim-`·`
  -separated. A real run fills the status slot (`✓/✗/⚠` from the exit code); a
  message that never ran (refusal/cd/interactive) **omits** it — never a fake
  status. The command lives in the header, so the body (line 2+) doesn't re-echo it
  and reads as a continuation ("`$ git branch`" → "isn't allowed to run"). Bare `>`
  (no command) is the one exception (`_msg`).
- **Colorblind-safe palette (Okabe-Ito), and keep it lean.** blue = success,
  red/vermillion = failure, amber = warning, teal = sethu icon / `[mode]` tag, orange =
  `⚠trust`. No green/red pairing. Differentiate with **weight or separators, not
  new hues** — every added color costs scannability. If tempted to add a color,
  don't.
- **Nothing is color- or glyph-only; a screen reader gets the full meaning.** Every
  distinguishing fact is also words (`✓ exit 0`, refusals omit the status slot,
  `[cwd]`, `⚠trust`), and `NO_COLOR`/`--color off` never drops information. For screen
  readers the `|^=^|` icon + `·✓✗⚠→•` glyphs are noise, so **`--plain on`/`SETHU_PLAIN`
  (`_plain_on`)** swaps them for a `sethu:` prefix + words — threaded as a `plain` arg
  through `_header`/`_msg`/`_reply` (and the status/cd/bullet/truncation builders), NOT
  by string-replacing the final output (that would mangle a command's own glyphs).
- **Color = sethu's *interpretation*; plain = *relayed* content.** Color the things
  sethu understands and gives meaning to (exit status, mode, warnings). Never
  recolor the command's own output — it's data sethu just carries. (But do append a
  trailing `\033[0m` when the output contains ANSI, so a colour the command left
  open doesn't bleed into the rest of the transcript — that's hygiene, not
  recoloring.)
- **Don't color routine messages.** Refusals and info (interactive, isn't-allowed,
  cd, state-builtin) are the `|^=^|` icon + `·` separator + **plain body** — they're
  normal outcomes, not alarms. Reserve color for *status* (✓/✗ exit) and *genuine
  problems* (e.g. the garbled-output warning is amber). Coloring every routine
  refusal would be warning fatigue.
- **`>` is free/private, `>>` costs tokens.** The whole product is about keeping
  output out of the model's context. Make the token cost visible at the moment it's
  incurred; never hide it.
- **Refusals teach, and lead with the safest path.** Say *why* it was refused, then
  the safest way to make it work (drop the write flag, run parts separately) before
  the generic `--allow`. A refusal is a mini how-to, not a dead end. Where a
  gated way exists, show it; where none does, `--allow <tool>` is the honest
  answer.
- **Degrade gracefully.** Unknown interactive/full-screen programs → a `--launch`
  hint, not garbled bytes or a hang. Every failure ends with an actionable next
  step.
- **Truthful feedback.** Only report success when something actually changed
  (`✔ added` / `already allowed` / `not in list`, not always `✔`).
- **Plain, natural language.** No em-dashes; commas/colons/parentheses instead.
  Concrete over jargon ("gated won't run it automatically", not "isn't
  auto-allowed"). Concise; say each thing once. **Scope:** this governs everything a
  *user* reads (tool output, refusals, `README.md`, `docs/use-cases.md`). The internal
  dev notes (`docs/design-guidelines.md`, `CLAUDE.md`) are working reference where
  density wins, so em-dashes there are fine; don't sweep them.

## Correctness

- **Every feature and CLI argument has a test.** Tracked in the coverage table at
  the top of `tests/test_sethu.py`, enforced by `TestCoverageEnforcement` (fails if
  any arg is untested). Add a row + test for anything new.
- **`docs/use-cases.md` is a contract, not decoration.** Every command shown there
  must behave exactly as documented: a "gated / out of the box" example must run
  without `--allow`, and an `--allow` / `--launch` / `--mode` example must work as
  described. Any change to the gating set (`GATED`), `is_gated`, `_DANGER`, the chain
  guard, `--allow` matching (`_matches`), interactive detection, or mode permissions
  MUST be re-checked against every use-case, because those examples are what a new user
  copies literally. When you change what's permitted, re-verify the doc and update it in
  the **same** change; when a use-case can be pinned as a behavior test, prefer that over
  trusting prose (e.g. `TestGatedFn.test_pipe_inside_quotes_is_not_a_chain`).
- **One canonical description, kept consistent and accurate.** The plugin's pitch lives
  in four places: `.claude-plugin/plugin.json` `description`, `.claude-plugin/marketplace.json`
  (both the marketplace `description` and the plugin-entry `description`), and the **GitHub
  repo "About"** (`gh repo edit --description "…"`). They must all tell the same story and
  never drift or go stale (they once still said "read-only by default" long after the model
  became "gated"). When the pitch or the model changes, update all four in the same change,
  match the README's framing, and keep the wording plain (no "read-only"/"execs" jargon).
- **Screenshots are docs too, keep them fresh.** `README.md` embeds `assets/*.png` captures
  of real sethu output: the `|^=^| · [mode] · status · $ cmd` header, the `>>` "shared … used
  tokens" note, and the refusal fix-menu. A change that alters any of those (the `_header`
  format, the palette, the refusal bullets, the `>>` confirmation, `--plain`/`--color` output)
  makes a screenshot stale and misleading. Flag it in the same change and re-capture. A
  screenshot can only be taken by a **human from a live Claude Code session**, so call it out
  explicitly rather than assuming it's covered, and keep the set consistent (same terminal
  width / zoom / theme so fonts render uniformly).
- **Validate values, not just types.** A hand-edited config must never crash or
  misbehave: coerce list entries to strings, fall back an invalid mode, reject an
  empty prefix, fall back malformed numbers.
- **Fail safe on bad input.** Fall back to defaults; don't crash the hook (it runs
  on every prompt).
- **Don't trust stale state.** When correctness depends on the current value,
  re-read/re-run rather than reusing an earlier result.

## Security

- **What auto-runs is mode-INDEPENDENT; mode only decides statefulness.** This is a
  load-bearing invariant — don't erode it:
  - **Auto-runs without `--allow`, in every mode:** the `GATED` tools **plus** the
    set-a-variable/alias builtins (`export`/`alias`/`unalias`/`unset`), all chain-guarded.
    None execute external code *themselves* — though in shell mode the state they set
    (`export PATH=…`, `alias ls=…`) can change what LATER commands resolve to. That's the
    user shaping their own shell (same as any terminal), not a sethu escalation; the gate
    still only auto-runs the known tool *names*.
  - **Never auto-runs, in any mode:** anything that executes code — `source`/`.` (they
    run a file's contents = arbitrary code) and every non-gated tool → requires
    `--allow` (the whole tool) or `--trust`.
  - `mode` (cwd/stateless/shell) changes only whether state *persists*, never *what is
    permitted*. A state builtin runs-and-persists in shell mode; in cwd/stateless it's a
    no-op, so show a concise "won't persist, use `--mode shell`" note (don't execute it,
    don't refuse it as forbidden). Presentation differs by mode; permission does not.
  - Do NOT make the auto-allow set mode-dependent (e.g. auto-permitting `source` only in
    shell mode) — it's confusing and, for `source`, it would open arbitrary execution in
    the default mode. If you're tempted to special-case a mode's permissions, don't.
- **The DEFAULT set is by TOOL and flag-safe; `--allow` is by TOOL at the user's
  discretion.** A tool auto-runs *without* `--allow` (is in `GATED`, the built-in default)
  only if NO flag/operand can make it write, delete, or exec — audited, enforced by
  `TestGatedSetIsFlagSafe`. There is deliberately **no per-flag policing** — a flag
  denylist is tedious AND leaky (it can't even see `uniq IN OUT` / `xxd IN OUT`
  positional-write operands). Tools that CAN write/exec via a flag (`git`, `find`, `fd`,
  `rg`, `sort`, `yq`, …) are NOT gated by default; the user opts into their **whole
  surface** with `--allow <tool>` (a launcher-warning fires) — that's user discretion, not
  a flag-safety claim, so a `--allow`'d tool need not be flag-safe. Gated is a safe
  *default* / guardrail, not a sandbox — the user can run anything via their terminal, `!`,
  `--allow`, or `--trust`.
  **Scope of the flag-safe guarantee:** it's a PER-COMMAND property and holds in
  cwd/stateless (fresh subprocess each command). In **shell mode** it can be voided by the
  user's own prior auto-run state — `alias ls=…` or `export PATH=…` redefine what a later
  gated name resolves to (M-2, audited-reproduced 2026-07-06). Decision: DOCUMENT, don't
  block — blocking `export PATH=`/aliases would gut shell mode (whose purpose is
  persistence; `source .venv/bin/activate` changes PATH too), and it needs the user to type
  that alias/export themselves (no external attacker can inject a `>` command). Documented
  in README §Safety + the `GATED` comment. Do NOT re-litigate as a bug without a new vector.
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
- **The shell-mode daemon is your own shell — no new privilege.** A per-session `bash`
  under your uid, reachable only over a **0600** Unix socket (`umask(0o077)` + `chmod`; it
  refuses to serve if not owner-only — fail closed). Anything that could reach it already
  runs as you, and it still passes the gate + chain guard. Idles out in 30 min.
- **Persisted runtime state fails safe on read.** The cwd file holds only a path; `get_cwd`
  validates it with `os.path.isdir` and falls back on anything torn/garbage/missing.
  Hardening the *write* (atomic replace, `0600`, `O_NOFOLLOW`) is tracked separately
  (config/cwd durability) — LOW, shared-machine-specific.

## Performance

- **The `UserPromptSubmit` hook runs on EVERY prompt.** Keep the non-sethu fast path
  cheap: decide with `json`/`os` only and DON'T import `_engine` for a normal
  message. sethu's own overhead should stay sub-millisecond.
- **Measure before optimizing.** Interpreter startup dominates; most in-process work
  is already sub-microsecond. Don't add per-prompt work for a micro-optimization.
- **Verify no degradation with the invariant test, not ms thresholds.** The fast path
  skipping `_engine` is pinned by `test_fast_path_skips_engine_import` (deterministic).
  Wall-clock is env-dependent (interpreter startup dominates and varies by machine), so
  these are a **same-machine reference, not a CI gate or a leaderboard**. When you touch a
  hot path, re-measure (`python3 -X importtime hooks/sethu_hook.py` + a `timeit` loop over
  `process()`) and update the table: shift `Current` into `Last`, put the new numbers in
  `Current`, and only lower `Best yet` if it's a real, correct improvement.

  | Metric | Last (2026-07-03) | Current (2026-07-06) | Best yet |
  | --- | --- | --- | --- |
  | normal-prompt overhead | ≈ 32 ms | ≈ 32 ms † | ≈ 32 ms |
  | — of which sethu's own code | < 1 ms | < 1 ms † | < 1 ms |
  | `> cmd` extra (bash spawn) | +4 ms | +4 ms † | +4 ms |
  | warm shell (shell mode) | ≈ 38 ms | ≈ 38 ms † | ≈ 38 ms |
  | `_maybe_sethu` (prefix gate) | ≈ 11 µs | ≈ 11 µs † | ≈ 11 µs |
  | `is_gated` / `_matches` | sub-µs ‡ | 5–11 µs | 5–11 µs ‡ |

  † Carried from 2026-07-03; on 2026-07-06 only `is_gated`/`_matches` was re-measured
  (the quote-aware `shlex` change). Re-measure the rest next time you touch the hot path.
  ‡ The old sub-µs was the pre-`shlex` naive `|` split, which had the quoted-pipe bug
  (fixed in #15). The 5–11 µs version is correct, still ~400× under the +4 ms bash spawn,
  and runs only on the `> cmd` path (never the every-prompt fast path) — so "faster" here
  would mean reverting a correctness fix. Correctness won; it's not a target to chase.

## Storage

- **Bound captured output** in RAM and on disk (a single `> yes` / `> cat big.iso`
  must not balloon memory or write a multi-GB temp file).
- **Every temp artifact sethu writes must be swept.** Anything under
  `sethu-*` (output logs, launch scripts, sockets, cwd files) is age-swept by
  `_sweep_temp`; a new artifact type must be added to it. Nothing grows unbounded.
- **Verify no degradation with tests, not numbers.** Storage guarantees are
  deterministic, so pin them: every `sethu-*` artifact type is proven swept by
  `TestSweep` (extend it when you add an artifact), and captured output is byte-capped
  (a cap test — arriving with the ST1 fix). No wall-clock or size "baseline" needed —
  these are exact assertions.

---

## Checklist for any change

- [ ] **Tested** — a test added/adjusted; coverage-table row updated; `TestCoverageEnforcement` green; full suite passes.
- [ ] **UX** — opens with the `|^=^|` icon (so sethu is instantly recognizable), colorblind-safe & no new hue, truthful, actionable, plain language, no em-dashes.
- [ ] **Correctness** — validates input, fails safe, doesn't rely on stale state.
- [ ] **Use-cases** — every `docs/use-cases.md` example still behaves as documented (gated ones run, `--allow`/`--launch`/`--mode` ones work); doc updated in this change if permitted behavior changed.
- [ ] **Screenshots** — if this changes the header / refusal menu / `>>` output / colors, the README `assets/*.png` are re-captured (human, live session) or flagged as needing it.
- [ ] **Security** — does it widen what runs? flags (not just names) audited? fails closed? trust still opt-in?
- [ ] **Performance** — no new work on the every-prompt path; fast path still skips `_engine`.
- [ ] **Storage** — output stays bounded; any new temp artifact is swept.
- [ ] `claude plugin validate .` passes.
