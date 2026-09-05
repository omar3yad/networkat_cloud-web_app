# Project Rule: Concise Messages, Alerts, and Validations

## Core Directive
All user-facing messages across the entire codebase (frontend templates, JavaScript handlers, alerts, toasts, modals, form validations, backend routes, flash messages, and API error responses) MUST always be concise, simple, clean, and punchy.

## Guidelines & Examples

### 1. Success & Action Alerts / Toasts
- `"Saved successfully"` (never verbose sentences like *"Settings saved and applied successfully!"*).
- `"Synced successfully"` (never *"Address lists / rules synchronized successfully"*).
- `"Deleted successfully"` (never *"Item was deleted successfully from the database"*).
- Confirm dialogs: `"Delete this rule?"`, `"Delete alias \"{name}\"?"` (never long *"Are you sure you want to permanently delete..."*).

### 2. Form & Field Validations
- Required fields: `"Required"` or `"Name required"`, `"Subnet required"`.
- Character limits: `"Max 200 characters"`, `"Max 64 addresses"`, `"Max 64 ports"`.
- Subnets / IPs: `"Invalid subnet"`, `"Invalid IP address"`, `"Invalid subnet mask"`, `"Only IPv4 supported"`.
- Hostnames / Domains: `"Invalid hostname"`, `"Invalid domain"`, `"Enter domain name"`.
- Duplicates: `"Name already in use"`, `"Subnet already in use"`, `"Duplicate item"`, `"Duplicate address"`, `"Duplicate alias"`.
- Mixed inputs: `"Cannot mix IPs and @alias"`, `"Only one alias allowed"`, `"Web Domain aliases not supported"`, `"Normal aliases not supported"`.

### 3. Backend Route & API Responses
- Error keys should carry minimal, clear strings (e.g. `{"error": "Unauthorized"}`, `{"error": "Name already in use"}`, `{"error": "Invalid subnet"}`).
- Avoid long error sentences or stack trace leaks to the client UI.
