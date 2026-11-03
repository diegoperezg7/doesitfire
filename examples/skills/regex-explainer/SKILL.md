---
name: regex-explainer
description: "Explains an existing regular expression token by token and lists strings it matches and does not match. Use when the user pastes a regex and asks what it does or why it fails to match."
---

# Regex explainer

1. Say which flavor you assume (PCRE, JavaScript, Python `re`) and why.
2. Walk through the pattern one token at a time in a table: token, meaning.
3. Give three example strings that match and three that do not.
4. Point out common traps you see: greedy quantifiers, unescaped dots,
   missing anchors, catastrophic backtracking.

Do not rewrite the regex unless the user asks for it.
