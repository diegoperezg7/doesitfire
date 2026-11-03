---
name: commit-message
description: "Writes git commit messages in Conventional Commits format (type(scope): summary, body, footer). Use when the user asks to write, draft, fix or improve a git commit message."
---

# Commit message

Write the commit message for the change the user describes.

1. Pick the type: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `build` or `ci`.
2. Add a scope in parentheses when the change is limited to one area, e.g. `feat(auth):`.
3. Summary line: imperative mood, lower case, no trailing period, 72 characters at most.
4. Leave one blank line, then a body that explains *why*, wrapped at 72 characters.
5. Breaking changes go in a `BREAKING CHANGE:` footer.

Return only the message inside a code block, ready to paste.
