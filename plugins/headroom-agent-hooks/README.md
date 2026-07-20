# HarryRoom agent hooks

> HarryRoom is a personal fork of [Headroom](https://github.com/chopratejas/headroom).
> This plugin is unchanged in behavior from upstream — only the display name/metadata
> differ. It still shells out to the `headroom` CLI, not a renamed binary.

This plugin exposes lightweight startup hooks for Claude Code and GitHub Copilot CLI.

The hooks call:

```bash
headroom init hook ensure
```

That hidden helper checks for a matching durable `headroom init` deployment and starts it
if needed. As of this fork, it also skips the network health probe entirely when a prior
call already confirmed the proxy healthy within the last 10 seconds — the hook fires on
every single Bash/PowerShell tool call, so probing every time added needless per-command
latency.
