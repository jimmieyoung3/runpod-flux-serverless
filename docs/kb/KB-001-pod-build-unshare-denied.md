# KB-001: Container build on a Pod fails with "unshare(CLONE_NEWUSER): Operation not permitted"

**Applies to:** Building container images inside a Runpod Pod (GPU or CPU) using
Buildah, Podman, or any tool built on the containers/storage stack.

## Symptoms

Your build fails immediately, before any layer is pulled:

```
Error during unshare(CLONE_NEWUSER): Operation not permitted
error: parsing PID "": strconv.Atoi: parsing "": invalid syntax
```

The failure is not specific to building. Even a read-only command fails the same
way:

```
$ buildah containers
Error during unshare(CLONE_NEWUSER): Operation not permitted
```

Adding `--isolation chroot` or `--storage-driver vfs` does not help, and neither
does running as root. You are already root.

## Cause

Runpod Pods run without the `CAP_SYS_ADMIN` capability, and the host kernels set
`kernel.apparmor_restrict_unprivileged_userns=1`. Together these deny the
`unshare(CLONE_NEWUSER)` system call.

Buildah and Podman re-execute themselves inside a new user namespace as one of
the first things they do at start-up. That happens *before* they read
`--isolation chroot`, so the flag that would have avoided namespaces never gets
a chance to apply. This is why the tool fails even on commands that do no work.

This is expected behaviour for a container running without that capability, not
a fault on your Pod.

## How to confirm

Run these three checks inside the Pod:

```bash
# 1. Are we in a user namespace already? "0 0 4294967295" means no.
cat /proc/self/uid_map

# 2. Is CAP_SYS_ADMIN present? Look for "!cap_sys_admin" in the IAB line.
capsh --print | grep -E '^Current'

# 3. Is the AppArmor restriction active? 1 means unprivileged userns is blocked.
sysctl kernel.apparmor_restrict_unprivileged_userns

# 4. Direct test. This fails if the restriction applies to you.
unshare -U true && echo "userns OK" || echo "userns BLOCKED"
```

If step 4 prints `userns BLOCKED`, this article applies.

## Resolution

Use a builder that does not create user namespaces. Kaniko works, because it
manipulates the filesystem directly rather than using runc.

Kaniko is published only as a container image, and you cannot run container
images on the Pod, so unpack it instead:

```bash
curl -sL "https://github.com/google/go-containerregistry/releases/download/v0.20.2/go-containerregistry_Linux_x86_64.tar.gz" \
  | tar -xz -C /usr/local/bin crane
mkdir -p /kaniko-src
crane export gcr.io/kaniko-project/executor:v1.23.2 - | tar -xC /kaniko-src
/kaniko-src/kaniko/executor version
```

Before you use it, read KB-003 and the warning below. Kaniko has a significant
side effect on the Pod it runs in.

## Important: Kaniko replaces the Pod's filesystem

Kaniko extracts your base image over `/`. That deletes the Ubuntu userland the
SSH daemon depends on, including its PAM and libc dependencies, so **SSH drops
about 60 to 90 seconds into the build and does not come back**. Adding
`--ignore-path` for `/etc/ssh` and `/usr/sbin/sshd` is not enough, because the
libraries they load are removed too.

Two consequences follow, and both matter:

1. **Let Kaniko push the image itself.** If you build to a local tarball with
   `--no-push --tarPath`, the finished image is stranded on a Pod you can no
   longer reach. Pass `--destination` and let it push to your registry.
2. **Run it detached and watch from outside.** Start it under `setsid` with
   output to a log file, then track completion against your registry rather than
   over SSH:

```bash
setsid nohup /kaniko-src/kaniko/executor \
  --force \
  --context dir:///root/build \
  --dockerfile /root/build/Dockerfile \
  --destination docker.io/<user>/<repo>:v1 \
  --single-snapshot \
  --ignore-path=/root \
  --ignore-path=/kaniko-src \
  > /root/kaniko.log 2>&1 < /dev/null &

# from your own machine, not the Pod:
crane manifest docker.io/<user>/<repo>:v1   # succeeds once the push lands
```

Terminate the Pod when the push completes. It is not usable afterwards.

## Alternatives

- **Build somewhere else and push to a registry.** Simplest option when you have
  the local disk and upload bandwidth for it.
- **Runpod's Bazel tutorial** at https://docs.runpod.io/tutorials/pods/build-docker-images
  builds images in a Pod using Bazel and crane, which avoids namespaces for the
  same underlying reason.

## Related

- KB-002: workers stay throttled after pushing a large image
- KB-004: keeping credentials out of an image built with Kaniko
