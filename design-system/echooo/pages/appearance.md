# Appearance — light by default

User-requested override (2026-09-04) to the legacy dark-only direction in MASTER.md.
Applies across the workspace, conversations, dialogs, sign-in, and guest pages.

- Default to light, independent of OS appearance. Keep the original dark/sage theme
  as an explicit choice, remembered in this browser and synchronized across tabs.
- Light mode: white working canvas, subtle gray sidebar, charcoal main actions,
  restrained green accents for identity and state. Keep the existing system font
  stack, spacing, content-first layout, and accessible interaction patterns.
- Semantic color tokens live in `web/theme.css`; do not hardcode dark colors in
  individual components. Text, placeholder, action, and input-boundary contrast
  have regression checks in `tests/test_theme.mjs`.
- Apply a saved choice before first paint through the external CSP-safe
  `web/theme.js`. Storage failures must not prevent using the application.
- Switching appearance does not navigate, reconstruct the conversation, request
  microphone access, or change data/permissions. Preserve drafts and voice state.
- Sidebar and workspace settings expose labeled Light/Dark choices with pressed
  states. Sign-in, invitation, and guest views also expose appearance controls.
- Preserve restrained button/menu interaction feedback and reduced-motion support;
  do not add sweeping page animations or decorations to the conversation canvas.
- Keep conversation Domains beside the title and before Context; show the first
  name plus the remaining count. Wrap within the header on small screens. Do not
  restore a separate settings strip or a redundant private-chat subtitle.
- All option menus use the shared select-only combobox, themed panel, subtle
  shadow, selected checkmark, and 44px rows. Use full readable option text,
  viewport-aware placement, and top-layer menus inside scrolling dialogs.
- Preserve keyboard selection, form values, disabled states, and dynamic choices.
  Escape cancels the menu without closing its parent dialog; Tab continues focus.
- Do not restore a separate Conversation settings icon. Keep Domains, Context,
  and More in the private-chat header. Voice options belongs beside Start voice,
  expands on demand, and never consumes another persistent settings row.
