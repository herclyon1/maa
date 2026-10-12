# OK-WW payload

`ark_overrides.tasks.py` is copied by the relay (`../okww_overlay.py`) into OK-WW's
`working/ok_tasks/ark_overrides.py`, where ok-script executes it at startup. It rebinds
methods on upstream's classes and carries method bodies derived from
[ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves),
which is **licensed AGPL-3.0**; copyright of those parts stays with the upstream authors.
The file runs inside OK-WW's own Python, not the relay's.

Nothing here replaces or edits an upstream source file any more. The stored upstream /
patched copies of `NightmareNestTask.py` and the `DailyTask.run` fragment were removed
on 2026-10-12, together with the relay code that put upstream's text back on the
machine, once the machine was checked clean (no source patch left, nest file upstream's own).

What the overrides change, and why: [../../../../../docs/OKWW-PATCHES.md](../../../../../docs/OKWW-PATCHES.md).

The changes are under AGPL-3.0 as well. The rest of this repository: root [LICENSE](../../../../../LICENSE).
