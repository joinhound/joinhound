# 0010. How equality matchers discover and resolve

## Context

`LinkMatcher.discover` and `resolve` receive column profiles and a small context. They do not receive the tabular source, the containment threshold, or a place to put evidence. A foreign key may also name several columns, while a profile describes one column. The specification does not say what `confidence` an exact match should carry.

## Decision

Each matcher is constructed with the `TabularSource` it reads. `ProfileContext.containment_threshold` defaults to 0.5, the same cutoff the profiler uses.

`declared_fk` discovers only a foreign key of one column on each side and returns confidence 1.0. Composite keys are skipped. `exact` samples at most 1,000 source values, measures how many distinct non-null values occur in the destination through `find_values(exact)`, and returns that ratio as confidence when it meets the threshold.

Both types resolve by searching the destination column for equal values. Every match scores 1.0. The lookup result is not stored.

## Alternatives

- Put the source on the context object. The context model would then depend on the source protocol.
- Treat any shared sample value as exact. Pairs below the containment cutoff would still be proposed.
- Split a composite foreign key into one candidate per column. A partial key would be approved on its own.
