# 0003. Minimal methods for unspecified extension protocols

## Context

T0.5 requires every extension protocol to exist with a docstring. The specification gives complete method lists for tabular sources, document sources, and link matchers. The other protocols are named, but their methods are not listed.

## Decision

Each unspecified protocol has the smallest method that matches its description: parse a document, recognize an image, review a candidate, embed texts, load and dump a model, read column descriptions, list stored links, resolve document roles, and authenticate a token. Later tasks can add parameters when an implementation needs them.

## Alternatives

- Leave the unspecified protocols empty. Callers would have no typed operation to implement.
- Invent the full future API now. Those methods would change as soon as the first implementation is written.
