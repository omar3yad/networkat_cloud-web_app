# Project Rule: UI Typography, Concise Messages, Alerts, and Validations

## 1. Strictly NO UPPERCASE in UI / CSS
- **Never use `text-transform: uppercase`** anywhere in CSS across the entire project.
- **Never write UI labels, buttons, headers, tags, badges, or dialog text in ALL CAPS (UPPERCASE)** in HTML, JavaScript, or CSS.
- **Always use standard Sentence case or Title case** (e.g. `Current version`, `Auto-update`, `Save changes`, `Close`, `Update available`).

## 2. Ultra-Concise Messages & Alerts
All user-facing messages across the entire codebase (frontend templates, JavaScript handlers, alerts, toasts, modals, form validations, backend routes, flash messages, and API error responses) MUST always be minimal, direct, simple, and punchy. Avoid verbose sentences.

### Examples:
- Success: `"Saved"`, `"Auto-update saved"`, `"Updated successfully"`, `"Synced successfully"`, `"Deleted successfully"`.
- Confirmations: `"Delete this rule?"`, `"Delete peer?"`.
- Form validations: `"Required"`, `"Name required"`, `"Subnet required"`, `"Invalid subnet"`, `"Name already in use"`.
- Backend error responses: `{"error": "Unauthorized"}`, `{"error": "Name already in use"}`. Avoid exposing internal stack traces or database IDs.
- Strictly avoid native browser dialogs (`alert()`, `confirm()`, `prompt()`). Always use project toasts or custom modal components.

