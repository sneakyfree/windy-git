# Windy Git gap analysis vs the DNA Strand Master Plan

`WINDY_GIT_GAP_ANALYSIS_2026-10-17.html` scores every codon of `DNA_STRAND_MASTER_PLAN.md` (as on main, 2026-10-17): 99 codons, 33 green / 26 yellow / 40 red, with the evidence for each. Scores were assigned by hand from evidence gathered that day.

`gap_build.py` is the generator that wrote it (`python3 gap_build.py out.html`). It is kept exactly as it ran, not maintained, and not linted by CI.

Both lived only in Windy 0's `~/windy-orchestra/specs/` until 2026-10-21, when they were salvaged here during the Windy 0 exit; the generator came from the 10-17 session log. The plan itself was always in this repo: its last change is `90643fe` (2026-09-23).
