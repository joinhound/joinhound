# Agent instructions

The task order and product rules live in `spec/spec.md` when that file is present in the workspace.

1. Work by stage and by task, in the listed order. One task is one branch and one pull request, with the task identifier in the title (`T1.3: exact matcher`). Start the next stage only after the current stage meets its exit criterion.
2. Before a task, re-read “Principles and constraints”, “Extension points”, and the section that defines the task. The project prohibitions always hold: no geographic-proximity links, no persistent record-to-record tables, and no writes to a customer data source.
3. Declare interfaces only in `core`. Register implementations through entry points. Every implementation passes the contract tests for its interface.
4. Where an open standard or a permissively licensed library exists, use it. Add a dependency only with an allowed license and a pinned version. Allowed licenses are Apache-2.0, MIT, BSD, ISC, PostgreSQL, PSF, and LGPL used only as an unmodified library. GPL and AGPL are not allowed.
5. Deliver every task with tests. Before finishing, `ruff`, `mypy`, `pytest`, `import-linter`, and the license check pass.
6. Sign every commit with `git commit -s`. A pull request without `Signed-off-by` fails the DCO check. If commits are missing a sign-off, sign the latest with `git commit --amend -s --no-edit`, or sign the branch with `git rebase --signoff main` and `git push --force-with-lease`.
7. If the specification does not answer a question, choose the simplest option and record it in `docs/decisions/NNNN-topic.md` (context, decision, alternatives). Stop and ask when the question concerns a project prohibition or a data format that users will see.
8. Names are fixed: package and repository `joinhound`, commands `joinhound` and `jh`, service schema `kg`, entry-point groups `joinhound.*`, and Ossie `vendor_name` `JOINHOUND`.
