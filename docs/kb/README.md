# Knowledge base

Customer-facing articles written from issues encountered while building and
deploying the FLUX.1-dev serverless endpoint in this repository. Each one
follows the same shape: what you see, what causes it, how to confirm it, and
what to do about it.

| Article | Issue |
| --- | --- |
| [KB-001](KB-001-pod-build-unshare-denied.md) | Container build on a Pod fails with `unshare(CLONE_NEWUSER): Operation not permitted` |
| [KB-002](KB-002-serverless-workers-throttled.md) | Serverless workers stay `throttled` and jobs sit in the queue |
| [KB-003](KB-003-first-request-times-out.md) | The first request to a new endpoint times out, later requests work |
| [KB-004](KB-004-keep-tokens-out-of-images.md) | Keeping Hugging Face and registry credentials out of your image |

Each article states plainly which parts are confirmed and which are the most
likely explanation, so you know how much to trust the diagnosis.

## Why these exist

These were written from real failures encountered while deploying the endpoint
in this repository, not from hypotheticals. Each diagnosis was confirmed with the
commands shown in the article. Where a cause is inferred rather than proven, the
article says so.
