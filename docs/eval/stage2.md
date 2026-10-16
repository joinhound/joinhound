# Stage 2 dirty columns

Forty generated rows in the shape of Pagila `customer.email`, `address.phone`, and `film.code`. The dirty copy changes the case of every email, the punctuation of every phone, and adds a `CODE-` prefix to every film code. Every tenth value also drops one character. The generator is `joinhound.dirty`. It does not rewrite the Pagila dump.

Resolution is the share of dirty values that find the clean row. `get_context` is asked the dirty value itself, and the gold row is the clean one reached through the link.

| Column | Matcher | Resolve recall |
| --- | --- | ---: |
| email | normalized (`fold`) | 0.900 |
| phone | normalized (`compact`) | 1.000 |
| code | fuzzy | 1.000 |

`get_context` recall on the three questions is 1.000. The four email typos are the misses: `fold` does not repair a deleted character, and those questions were not in the three-question sample. A phone typo that deletes punctuation still compacts to the same digits, so phone recall stays 1.

No model was called. This is the stage 2 measurement.
