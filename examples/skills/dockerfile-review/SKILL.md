---
name: dockerfile-review
description: "Reviews a Dockerfile for image size, build cache use and security (root user, pinned base images, leaked secrets). Use when the user shares a Dockerfile and asks for a review or how to make the image smaller or safer."
---

# Dockerfile review

Review the Dockerfile in this order and report findings as a numbered list,
most important first, each with the line and a concrete fix:

1. Base image: pinned tag or digest, slim or distroless variant.
2. Layer order: dependency manifests copied and installed before source code.
3. Size: package manager caches removed in the same layer, multi-stage builds.
4. Security: non-root `USER`, no secrets in `ENV`, `ARG` or copied files.
5. Runtime: `HEALTHCHECK`, exec-form `CMD`/`ENTRYPOINT`, explicit `EXPOSE`.
