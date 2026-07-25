# Repository guidance for coding agents

## Product

This repository contains two related clients:

- The original Python/NiceGUI desktop prototype at the repository root.
- The competition-oriented native HarmonyOS application in `harmony-app/`.

The HarmonyOS client runs without a project-owned server. It searches a bundled,
read-only legal index locally and calls a user-configured OpenAI-compatible API.

## Important paths

- `harmony-app/entry/src/main/ets/pages/Index.ets`: primary ArkUI page and flows.
- `harmony-app/entry/src/main/ets/services/`: API, storage, attachment, search,
  and service-card state services.
- `harmony-app/entry/src/main/resources/rawfile/law_index.json`: generated index.
- `tools/kb_builder/`: offline corpus converter.
- `docs/contest/`: implementation and acceptance records.

## Safety rules

- Never commit API keys, signing files, signing passwords, local SDK paths, user
  conversations, attachments, or DevEco caches.
- Keep `build-profile.json5` free of machine-specific signing material.
- Treat source corpora as read-only inputs; generated indexes belong under the
  HarmonyOS raw resources directory.
- Preserve source name, article, and status metadata for citations.
- Keep the visible legal disclaimer and the corpus-validity warning.

## Engineering rules

- Preserve both quick consultation and case-analysis modes.
- Keep multi-turn context and validate model citation IDs before display.
- Handle missing configuration, timeouts, HTTP failures, malformed JSON, and
  large attachments without crashing.
- Do not add a project server unless a task explicitly changes the architecture.
- Prefer small changes and run the narrowest relevant checks.

## Verification

For HarmonyOS changes:

1. Run `./tools/harmony/build-debug.sh`.
2. Test the affected flow on a HarmonyOS 6.1 simulator or device when possible.
3. Do not commit HAP files or signing material.

For Python changes:

1. Run the relevant test file or `python -m unittest discover -s tests`.
2. Keep generated corpus files and user data out of Git.
