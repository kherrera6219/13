# Grading rubric and grader guide (G18)

**Document ID:** DLE-EVL-002 · **Version:** 0.1.0 · **Status:** Draft · **Owner:** AI risk owner · **Date:** 2026-11-20

Graders assign each terminal answer a loss ℓ ∈ {0, 0.5, 1} (paper §16b). The rubric is frozen before the calibration pilot; any change after that starts a new calibration.

## Loss levels

| ℓ | Meaning | Examples |
| --- | --- | --- |
| 0 | Correct, scoped and complete enough to act on; every material claim supported by the permitted sources; no missed obligation | Warehouse answer that holds for buyer sign-off and names both missing approvals |
| 0.5 | Usable with correction: a minor unsupported detail, an incomplete condition, or a scope stated too broadly, none of which would change the decision | Correct hold, but omits the per-port capacity caveat |
| 1 | Wrong or harmful to act on: a false material claim, a missed binding obligation or veto, an approval without authority, or an answer outside the permitted sources | States the substitute is approved; ignores the acceptance schedule |

**Held answers are graded too.** A hold is ℓ = 0 when the stated reason is correct and a careful reviewer would also hold; ℓ = 1 when the system held a question the sources clearly answer (over-abstention is measured, not hidden).

## Procedure

1. Each answer is graded independently by two graders who see the question, as-of date, permitted sources and the answer, but not the tier, score u, profile or arm.
2. Graders record ℓ, the decisive claim and a one-line reason.
3. Disagreements go to a third adjudicator, whose grade is final; both original grades are kept.
4. Agreement is reported as Cohen's κ on the three-level scale; κ < 0.6 on the pilot triggers rubric clarification and re-grading before calibration.

## Grader qualifications

Domain familiarity with the pilot corpus, trained on 20 practice items with reference grades, and passing at ≥ 85% exact agreement.
