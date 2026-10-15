# Contributing

Joinhound is licensed under the Apache License 2.0. Contributions are welcome.

## Developer Certificate of Origin

Every commit must include a `Signed-off-by` line. Create it with:

```console
git commit -s
```

That line certifies the [Developer Certificate of Origin](https://developercertificate.org/), version 1.1:

```text
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

1 Letterman Drive
Suite D4700
San Francisco, CA, 94129

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.

Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

A pull request without a sign-off on every commit will fail the DCO check. To add a missing sign-off on the latest commit, run `git commit --amend -s --no-edit`. To sign every commit on a branch, run `git rebase --signoff main` and then `git push --force-with-lease`.

## Development

The project uses Python 3.12 and [uv](https://docs.astral.sh/uv/).

```console
uv sync
uv run joinhound --help
uv run pytest
```

Do not commit secrets. Local credentials belong in `.env`, which is ignored by git.
