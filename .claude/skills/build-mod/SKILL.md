---
name: build-mod
description: Prompt the user to rebuild TerraBlind in-game and wait for confirmation. Use after any change to ModSources/TerraBlind/*.cs. Posts the standard "请在游戏内 /build TerraBlind，完成回复 1" handshake and pauses until the user replies.
---

## When to use

- After any Edit/Write to a file under `/Users/lhy/Library/Application Support/Terraria/tModLoader/ModSources/TerraBlind/**`
- Before running any test/script that depends on new mod behavior

## What the skill does

Emit exactly this line, then stop:

```
请在游戏内 /build TerraBlind，完成回复 1。
```

After the message is sent, **do not call further tools** in the same turn. Wait for the user's `1` (or a description of build errors). When they reply:

- `1` → build succeeded, continue with whatever was queued next
- error text → read the error, suggest a fix to the code, then re-invoke this skill

## Don'ts

- Don't try to build the mod yourself — there is no headless build path; only the in-game `/build` command works.
- Don't bundle this prompt with other questions in the same message — the user will miss it.
- Don't skip this skill after `.cs` edits, even if you're "pretty sure" it'll compile.
