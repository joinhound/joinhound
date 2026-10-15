# Package registry setup

The names `joinhound` on PyPI and npm were available when checked on
2026-10-15. Registry availability can change at any time, so complete both
registrations promptly.

## P.3 — PyPI Trusted Publishing

1. Create or sign in to a PyPI account and enable two-factor authentication.
2. Open **Your projects → Publishing** and add a pending publisher with:
   - PyPI project name: `joinhound`
   - Owner: `joinhound`
   - Repository: `joinhound`
   - Workflow name: `publish-pypi.yml`
   - Environment name: `pypi`
3. In the GitHub repository, create an environment named `pypi`. Add required
   reviewers if release approval is desired.
4. Merge the workflow and package scaffold before creating the first tag.
5. Create and push tag `v0.0.1`. The workflow builds and publishes the package
   without a long-lived PyPI token.

Do not add a PyPI API token to GitHub secrets; Trusted Publishing uses GitHub
OIDC.

## P.4 — npm reservation

The package stub is in `packages/npm-reservation`.

1. Create or sign in to an npm account, verify the email address, and enable
   two-factor authentication for writes.
2. Authenticate locally:

   ```console
   npm login
   npm whoami
   ```

3. Inspect the exact tarball, then publish it:

   ```console
   npm pack --dry-run ./packages/npm-reservation
   npm publish ./packages/npm-reservation --access public
   ```

4. Verify the owner and published version:

   ```console
   npm owner ls joinhound
   npm view joinhound name version repository
   ```

Never commit `.npmrc`, npm tokens, recovery codes, or PyPI credentials.
