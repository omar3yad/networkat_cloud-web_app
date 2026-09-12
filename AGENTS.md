# Workspace Agent Rules

## 1. Strictly NO UPPERCASE in UI & CSS
- **Never use `text-transform: uppercase`** in any CSS file or style attribute.
- **Never write UI labels, buttons, headers, badge text, or dialog copy in ALL CAPS / UPPERCASE**.
- **Always use standard Sentence case or Title case** (e.g. `Current version`, `Auto-update`, `Save changes`, `Close`).

## 2. Ultra-Concise Client-Facing Messages
- All user-facing toasts, modals, alerts, badges, and validation error texts must be as short, direct, and minimal as possible (e.g., `"Saved"`, `"Auto-update saved"`, `"Updated successfully"`).
- Never write verbose explanations or long paragraphs for success/error alerts.
- Strictly avoid native browser dialogs (`alert()`, `confirm()`, `prompt()`).

## 3. Clean Architecture & Security
- Never expose internal database IDs, stack traces, or raw backend errors to the end user.
- Keep controllers thin and delegate logic to service/repository layers.
