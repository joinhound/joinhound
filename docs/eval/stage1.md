# Stage 1 baseline

Twenty Pagila questions, gold rows in `tests/eval/gold/pagila_questions.json`. The source is the pinned Pagila revision `ce6e114236bb828e5ec0dc835f65f1bf1b9179f5`. Both agents used `claude-sonnet-5-5`.

## get_context

Declared foreign keys, engine defaults, one call per question. Precision and recall are macro-averages. The source name in a URI is ignored.

- recall@budget: 0.704
- precision: 0.126
- latency p50: 120 ms
- latency p95: 187 ms

The MVP targets are recall at least 0.8, precision at least 0.6, and p95 under 2 seconds. Precision is low because a hub such as language pulls in rows the question did not ask for.

| Question | Recall | Precision | ms |
| --- | ---: | ---: | ---: |
| ace-goldfinger-actors | 0.556 | 0.156 | 187 |
| adaptation-holes-actors | 0.545 | 0.188 | 139 |
| airport-pollock-actors | 0.556 | 0.156 | 120 |
| alice-fantasia-actors | 0.556 | 0.102 | 165 |
| alamo-videotape-actors | 0.556 | 0.147 | 120 |
| ace-goldfinger-language | 1.000 | 0.062 | 116 |
| adaptation-holes-language | 1.000 | 0.062 | 114 |
| airport-pollock-language | 1.000 | 0.062 | 119 |
| ace-goldfinger-categories | 1.000 | 0.189 | 106 |
| airport-pollock-categories | 1.000 | 0.184 | 111 |
| alice-fantasia-categories | 0.571 | 0.082 | 162 |
| bob-fawcett-films | 0.510 | 0.366 | 126 |
| chris-depp-films | 0.512 | 0.231 | 129 |
| minnie-zellweger-films | 0.413 | 0.257 | 130 |
| mary-smith-home | 0.500 | 0.027 | 131 |
| patricia-johnson-home | 0.500 | 0.042 | 230 |
| linda-williams-home | 0.500 | 0.022 | 145 |
| sasebo-country | 1.000 | 0.041 | 29 |
| abha-country | 1.000 | 0.042 | 55 |
| ace-goldfinger-stores | 0.800 | 0.108 | 109 |

## Agents

An answer is confirmed when it cites at least one row a tool returned. Answer recall is the share of gold rows cited in the final text. The MVP target for confirmed answers is 0.95. The three filmography questions score 0 because neither agent cited the full film list.

| Agent | Answer recall | Confirmed answers |
| --- | ---: | ---: |
| joinhound MCP | 0.840 | 0.850 |
| schema + SELECT | 0.840 | 0.850 |

Recall gap (joinhound minus SQL): +0.000. Confirmed-answer gap: +0.000.

The gaps are not both at least 10 percentage points in joinhound's favor. The specification then moves documents ahead of fuzzy matching.

| Question | joinhound recall | joinhound confirmed | SQL recall | SQL confirmed |
| --- | ---: | --- | ---: | --- |
| ace-goldfinger-actors | 1.000 | yes | 1.000 | yes |
| adaptation-holes-actors | 1.000 | yes | 1.000 | yes |
| airport-pollock-actors | 1.000 | yes | 1.000 | yes |
| alice-fantasia-actors | 1.000 | yes | 1.000 | yes |
| alamo-videotape-actors | 1.000 | yes | 1.000 | yes |
| ace-goldfinger-language | 1.000 | yes | 1.000 | yes |
| adaptation-holes-language | 1.000 | yes | 1.000 | yes |
| airport-pollock-language | 1.000 | yes | 1.000 | yes |
| ace-goldfinger-categories | 1.000 | yes | 1.000 | yes |
| airport-pollock-categories | 1.000 | yes | 1.000 | yes |
| alice-fantasia-categories | 1.000 | yes | 1.000 | yes |
| bob-fawcett-films | 0.000 | no | 0.000 | no |
| chris-depp-films | 0.000 | no | 0.000 | no |
| minnie-zellweger-films | 0.000 | no | 0.000 | no |
| mary-smith-home | 1.000 | yes | 1.000 | yes |
| patricia-johnson-home | 1.000 | yes | 1.000 | yes |
| linda-williams-home | 1.000 | yes | 1.000 | yes |
| sasebo-country | 1.000 | yes | 1.000 | yes |
| abha-country | 1.000 | yes | 1.000 | yes |
| ace-goldfinger-stores | 0.800 | yes | 0.800 | yes |
