# Dirty Pagila-shaped columns

The stage 2 check dirties emails, phones, and codes instead of loading the Pagila dump and updating it. The shapes are the Pagila columns the specification names: customer email, address phone, and a film code. Forty rows are enough to apply a typo to every tenth value and to score resolution without a database.

`get_context` is scored on one non-typo value from each column. The query is the dirty string stored on the intake row, and the gold URI is the clean row the link walks to.
