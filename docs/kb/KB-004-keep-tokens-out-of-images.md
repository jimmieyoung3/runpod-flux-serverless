# KB-004: Keeping Hugging Face and registry credentials out of your image

**Applies to:** Any image that downloads gated model weights at build time, and
anyone pushing a model image to a registry.

## The problem

Gated repositories such as `black-forest-labs/FLUX.1-dev` need an authenticated
download. The obvious approach is a build argument:

```dockerfile
# Do not do this
ARG HF_TOKEN
RUN HF_TOKEN=${HF_TOKEN} python download_weights.py
```

Build arguments are recorded in the image history. Anyone who can pull the image
can read the token back out:

```bash
docker history --no-trunc <image>
crane config <image> | jq '.history'
```

A private repository reduces the audience but does not fix it. Anyone you later
share the image with inherits your token.

## Option 1: BuildKit secrets, when you have BuildKit

The token is mounted only for the command that needs it and never enters a
layer:

```dockerfile
# syntax=docker/dockerfile:1.7
RUN --mount=type=secret,id=hf_token \
    python /app/builder/fetch_model.py
```

```bash
export HF_TOKEN=hf_...
docker build --secret id=hf_token,env=HF_TOKEN -t <user>/<repo>:v1 .
```

Have the script read `/run/secrets/hf_token`, falling back to the environment
for local runs.

## Option 2: Fetch the weights before the build

Kaniko does not implement `RUN --mount=type=secret`, so if you are building in a
Runpod Pod (see KB-001) the above is unavailable. Download the weights into the
build context first, then copy them in. The build itself never authenticates:

```bash
# outside the image build, where the token is just an environment variable
HF_TOKEN=hf_... python scripts/fetch_weights_local.py ./weights
```

```dockerfile
# inside the Dockerfile, no secret needed
COPY weights/ /models/flux/
```

The cost is disk. The weights exist twice during the build, once in the context
and once in the image, so size your build host accordingly. For a 33.7 GB model
the build peaks near 120 GB.

Add the weights directory to `.gitignore` so it never reaches source control.

## Verify rather than assume

Check the published image before you trust it. This reads the image config and
searches it for token-shaped strings:

```bash
crane config <user>/<repo>:v1 | grep -aoE 'hf_[A-Za-z0-9]{15,}|dckr_pat_[A-Za-z0-9_-]{10,}' \
  && echo "TOKEN FOUND" || echo "clean"
```

Also check your git history, especially on a public repository:

```bash
git log --all -p | grep -nE 'hf_[A-Za-z0-9]{15,}|BEGIN (RSA|OPENSSH) PRIVATE'
```

## Registry credentials

To pull a private image, a Serverless endpoint needs a container registry
credential, which you add in the Runpod console or through the API. Use a
registry access token scoped to read, not your account password, and remove the
credential when the deployment is retired.

## Licensing note

Check what your model licence permits before pushing. FLUX.1-dev is covered by a
non-commercial licence that does not allow redistributing the weights, so an
image containing them belongs in a private repository.

Watch out for one detail: pushing to a repository that does not exist yet
creates it, and on Docker Hub the default is public. Create the repository and
set it private **before** your first push.

## Related

- KB-001: container build fails on a Pod with an unshare error
