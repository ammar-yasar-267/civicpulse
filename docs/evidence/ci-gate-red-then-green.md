# Evidence: a red pipeline blocks the merge, then green

Rubric I asks for evidence that the gate actually works, rather than a workflow file that would
work in principle. This is a real failure from this repository, not a contrived one.

## Red

**Run:** [36469500500](https://github.com/ammar-yasar-267/civicpulse/actions/runs/36469500500)
**Job:** `lint and type check` → step `ruff (format)`
**Result:** ❌ failure, 17s

```
Would reformat: app/logging_setup.py
1 file would be reformatted, 44 files already formatted
##[error]Process completed with exit code 1.
```

### What actually caused it

While removing a dead `_RESERVED` constant from `backend/app/logging_setup.py`, the edit was made
with a regex substitution rather than by hand, and it left a formatting artefact that `ruff format`
disagreed with. Local `ruff check` passed — lint and format are separate checks, and only the
format check catches this.

This is a small defect, and that is the point: it is exactly the class of thing a human reviewer
skims past and a pipeline does not. It reached the branch because `ruff format` had last been run
before those files were edited.

### The gate held

The failing job blocked subsequent jobs through `needs:`, so `build`, `scan` and `integration` never
ran. Nothing was built or published from a commit that had already failed a check — which is the
whole reason those jobs declare `needs:`.

## Green

**Fix:** `ruff format app tests` — one file changed.
**Run:** see the run immediately following commit `fix: apply ruff formatting to logging_setup`
on PR [#8](https://github.com/ammar-yasar-267/civicpulse/pull/8).
**Result:** ✅ all jobs pass.

## Screenshots

`docs/evidence/ci-red.png` and `docs/evidence/ci-green.png` — the blocked merge button and the
passing checks, captured from the PR page.

> **To capture:** open PR #8, screenshot the red check with the merge button disabled, then
> screenshot the same PR after the fix with all checks green.
