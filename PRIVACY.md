# Privacy

sethu runs entirely on your machine.

- **No data collection.** No telemetry, analytics, or tracking of any kind.
- **No network access.** sethu makes no network calls of its own. (Commands you
  choose to run might, but sethu itself never phones home.)
- **Everything stays local.** Configuration lives in `~/.claude/sethu.json`, and
  temporary files (command-output logs, launch scripts, sockets) are written to your
  local temp directory and cleaned up automatically.
- **Your commands stay with you.** A `>` command's output is shown only to you and
  never sent to the model; `>>` shares output with Claude only because you asked it to.

sethu is pure Python standard library with no third-party dependencies, so there is
nothing bundled that could collect or transmit data.
