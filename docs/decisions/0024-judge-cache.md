# Judge cache and the OpenAI SDK

The judge sends column names, the match type, and the evidence already stored on a candidate. A disabled judge returns no verdict, and the proposal stays for a person. A verdict that is not meaningful drops the proposal. Confidence at or above 0.95 is stored without a model call.

`judge.redact` replaces values of configured sensitive columns with the same letter-and-digit pattern used for column fingerprints. The cache key is a hash of that redacted prompt. The verdict is kept in memory and in `kg.judge_cache`, so a repeated profile does not call the model again.

The `openai` package is the SDK named in the specification. Its tree includes `sniffio` (Apache-2.0 or MIT) and `tqdm` (MPL-2.0 and MIT). Those two license strings are accepted as transitive exceptions.
