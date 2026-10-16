# Column to document links

Discovery searches sampled column values as phrases. A value counts only when
it occurs in at most half of the fragments in the collection (or in the only
fragment, when the collection has one). The candidate is kept when at least
30% of the sample is that rare. The fraction is the confidence, and the mean
IDF of those values is stored on the candidate.

Resolution searches the same passages: a phrase hit scores 1, and a miss falls
back to word trigram similarity of at least 0.6. The other direction builds an
Aho-Corasick automaton from the column and returns rows whose values occur in
one fragment. The profiler does not call this matcher yet, because it still
walks column pairs only. Callers pass the passages to search, which keeps the
matcher off the database.
