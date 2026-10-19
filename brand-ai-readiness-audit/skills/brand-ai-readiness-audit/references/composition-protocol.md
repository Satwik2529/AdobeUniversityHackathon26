# Composition protocol

The Agent Skills specification defines the single-skill format. It does **not** define
skill-to-skill invocation — the marketplace manifest is this contest's own convention.
So the entrypoint must not assume the harness can dispatch to a sibling skill. Three
paths produce the same report. Use the first that works.

## Path 1 — Agent-native activation (preferred)
Activate the sibling skill by the `id` in `marketplace.json` and pass it the snapshot
path. Use when the runtime supports loading more than one skill in a session.

## Path 2 — Relative-path reading (always available)
Read `../<skill-id>/SKILL.md` and follow its procedure yourself. `marketplace.json`
gives the exact path for every skill. This needs nothing from the harness but file reads.

## Path 3 — Direct script execution (deterministic floor)
Every detector ships a runnable script with a stable interface:

```bash
python3 skills/<skill-id>/scripts/<check_script>.py \
  --snapshot audit-output/snapshot.json \
  --out audit-output/findings-<skill-id>.json
```

All detector scripts accept `--snapshot` and `--out`, write a JSON array of findings to
`--out`, print a one-line summary to stderr, and exit 0 on success, 2 on bad arguments,
3 on an unreadable snapshot. Merging their outputs yields a complete report even if no
sub-skill was ever activated.

## Merge step

```bash
python3 scripts/merge_findings.py \
  --snapshot audit-output/snapshot.json \
  --findings audit-output/findings-*.json \
  --opportunities audit-output/opportunities.json \
  --out audit-output/report.json
```

`merge_findings.py` is the only place severity normalisation, deduplication, correlation
and ranking happen. Detectors propose; the entrypoint decides.

## Ordering guarantee
Detectors run in funnel order, but their findings are re-sorted deterministically at
merge time, so a different execution order cannot change the report.
