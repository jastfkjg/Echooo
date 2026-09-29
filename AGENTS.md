# Project Guidelines

## Frontend UI and copy

- Keep pages simple, focused, and easy to scan. Help users quickly identify the most important information and primary action.
- Use concise headings, labels, and button text. Avoid redundant descriptions, repeated information, long instructional paragraphs, and unnecessary explanatory copy.
- Prefer clear visual hierarchy, spacing, and intuitive controls over additional text. Do not add explanations for actions that are already self-explanatory.
- Show secondary guidance only when needed, such as contextual help, tooltips, or expandable details. Keep essential requirements, errors, and recovery instructions brief and visible at the relevant step.
- Prioritize reading comfort and reduce cognitive load whenever creating or updating a page.
- Write all application-authored, user-facing frontend text in English, including labels, buttons, placeholders, tooltips, validation messages, and empty states. Preserve user-provided content in its original language.

## LLM prompts

- Write and maintain all application-authored LLM prompts in English, including system instructions, developer instructions, prompt templates, and embedded task instructions.
- Preserve user input and source material in their original language when inserting them into prompts.

## Classification development principle

Fix classification errors through general semantic criteria, contextual evidence,
and representative evaluations. Do not hardcode a reported sentence, keyword list,
punctuation pattern, or an example-specific prompt rule to force a category.
Keep application prompts in English and preserve source material in its original
language. Mechanical validation may enforce schemas and evidence integrity; category
meaning must be assessed from context. Human category corrections must be persisted
with an audit history.
