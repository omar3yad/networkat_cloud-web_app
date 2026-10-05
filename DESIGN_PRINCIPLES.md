# Design principles

How UI work is done in this project, and the taste behind it. Distilled from the Log settings redesign (system logs modal, Oct 2026), which is the reference implementation: `client/static/js/system_logs.js`, `client/static/css/system_logs.css`, `client/templates/system_logs.html`.

Read this before any client-portal UI work. The message-copy rule in `.agents/rules/messages_and_validation.md` still applies on top of it.

## 0. The spirit

The owner designs by feel and corrects by detail. The goal of this file is to get the detail right the first time, so a screen does not need a round of "the icon appears too early", "the height changes", "the data disappeared".

The spirit in one paragraph: **a quiet interface that never surprises.** Every control says what it will do, and keeps saying it. Nothing jumps, nothing vanishes, nothing animates out of order. Controls that belong together are built from one measurement. A user can never enter a value that will be rejected, and when something is unavailable they can still see it and see why. Everything is small, light, and calm, and it works on a phone as well as on a desktop. Sections 1 to 7 are the rules; section 8 is the checklist to run before showing anything.

## 1. How to work on a design request

1. **Show before you build.** Make samples first (a private Artifact page, 3 options when the choice is open) and wait for a pick. Do not touch project files while the design is still being discussed.
2. **Implement only on an explicit go ("نفّذ").** An answer that merely repeats your question is not a go.
3. **This host is production.** Editing files changes nothing live until the user deploys. Never rebuild, restart or `docker cp` into the running container yourself. The user deploys with their own `@web_update` alias, which copies the *whole* working tree into the container, reloads gunicorn and syncs the standby; the permission system blocks Claude from running it.
4. **Iterate in small steps.** The user reacts to screenshots with precise, small corrections. Make exactly that change, keep every earlier decision, and do not "improve" other things on the way.
5. **Do not remove what was not asked to be removed.** Adding an icon is not moving an icon. If a request is ambiguous, state the interpretation you took and how to flip it.
6. **Offer icon choices.** When an icon is needed, show about 10 Font Awesome candidates in context (large and at real size) and let the user pick. Keep an existing icon the user likes (`fa-cog` for the Log settings title).
7. **Report honestly.** Say what was checked (syntax, ids) and what was not (no browser on the host, so nothing was seen rendered).
8. **Talk to the user in Arabic.** Code, UI copy and this file stay in English.

## 2. Visual taste

- **Minimal and calm.** No cards-in-cards. Rows separated by one hairline (`var(--nk-border)`). Quiet text, no decoration for its own sake.
- **Contrast is a state, not a default.** Tints, dividers and shadows appear only when they mean something (the sticky bar gets its divider and a faint button tint only once the list is scrolled). When asked for "light contrast" it means very light, and on the label or control, not the whole band.
- **Compact controls.** Inputs about 30px high (32px on phones), borders thin, widths sized to the value (Days 88px, Max 112px, Level 132px), not stretched across the row. Keep the browser's native number spinners.
- **Dropdowns match the project.** Never a native `<select>` for a styled choice. Use the shared popover menu (`.sl-menu`): white card, 10px radius, soft shadow, very light separators between options, current option tinted.
- **Value-coded things reuse existing colors.** Log levels are the pills from `.sl-level-*` (`--sl-*` variables), shown in both the button and the menu.
- **Time and date formats.** 24-hour clock, dates as `YYYY-MM-DD` (the site's ISO style). No AM/PM, no locale-dependent date text. A browser `datetime-local` or `type=date` shows locale text, so show the value in your own read-only field and put the native picker invisibly on top.
- **Accent colors.** Blue = primary (`--nk-blue-primary`). Amber `#d97706` = paused. Locked/disabled = grey, but still visible.
- **Project theme is light only.** There is no dark mode in the client portal; do not add one unless asked.

## 3. Behavior rules

- **Layout never jumps.** A state change must not move controls or change a row's or modal's height. Examples: the controls sit at the title line and the row keeps one summary line; the For and Until tabs share one grid cell so the modal keeps the taller tab's height; the two tabs' fields line up (label above both).
- **Disabled does not mean gone.** Off, locked or read-only things stay readable (fade, grey, lock glyph). The whole lower part of a screen shut by a master switch gets a frosted veil with one short message, and is `inert` (no taps, no Tab).
- **One control, one meaning.**
  - A paused category shows its switch *off* in amber with a pause glyph on the ball. The round pause button disappears, and resuming is done only by flipping that switch. No play icon anywhere.
  - Locked rows show a lock on the switch ball, and their dependent field (min level) is read-only with a lock.
- **Animations are sequenced.** A glyph that belongs on the switch ball fades in only after the ball settles (delay equals the slide time), and hides at once on the way out.
- **Prevent bad input, then explain.** Do not just flag out-of-range values. Constrain the pickers (`min`/`max`, dates outside the range not selectable), clamp a committed value (blur/Enter/spinner) to the nearest allowed one, and disable the action while invalid. The message names the real range, for example `Pick from <earliest> to <latest>`. Limits come from the device (`config.bounds`), never hard-coded guesses.
- **Show the other tab's value.** In a two-way input (For / Until) the tabs stay in sync live, and each shows the other's value (`Until 2026-10-07 22:40` on For, `For 1 d 12 h` on Until).
- **Live context.** A custom time picker shows a live clock (HH:MM:SS) so the user sees what "now" is.
- **Expand all.** Long lists of collapsible rows get an Expand all / Collapse all control on a sticky bar, left aligned.

## 4. Sizing and mobile

- **Pause button and switch are one size.** Both come from a single variable (`--sl-ctl`, 22px desktop, 24px phone): button diameter = switch height, switch width = 1.7 x height, ball = height - 6px. Change the variable, never one of them.
- **Phones (about 400px) are first-class.** Every design must work at that width with no horizontal scroll: 1rem gutters, rows that truncate with an ellipsis instead of wrapping, three-column field grids that shrink. Touch targets get a small bump on phones (half of what feels big), and tiny links get an invisible larger hit area (`::after { inset: -8px -4px }`).
- **Keep it to what was asked.** If a size is "too big", reduce by half the last increase, not to the start.

## 5. Copy

Terse, per `.agents/rules/messages_and_validation.md`. Short labels (`Keep (days)`, `Max entries`, `Min level`), short status (`System logs are off`, `Paused until 2026-10-07 22:40`), short errors that give the fix.

## 6. Gotchas learned the hard way

- `client/static/css/system_logs.css` has `.sl-page [hidden], .sl-widget [hidden] { display: none !important; }`. A `hidden` attribute therefore always wins. To hide without collapsing layout (tabs sharing a cell), toggle a class that sets `visibility: hidden`.
- `.sl-input` (and other controls) use `transition: var(--nk-transition)` = `all`. That also animates the *inherited* `visibility`, so inputs inside a hidden tab linger for 0.25s and look like overlap. Turn transitions off inside such containers.
- `.modal-card` has a `transform` and `.modal-overlay` a `backdrop-filter`, so `position: fixed` descendants resolve against them. Popover menus are appended to the overlay (which fills the viewport) and positioned from `getBoundingClientRect()`. Close them on scroll, outside click and Esc.
- A sticky bar inside a padded scroll container shows a gap above it. Give the scroll body `padding-top: 0` and let the bar own its padding, and make the bar full-bleed with a negative inline margin.
- A CSS custom property defined in terms of itself (`--x: var(--x)`) silently invalidates and makes controls vanish. Define tokens with literal values.
- The host has no Node. Syntax-check JS in a throwaway container, for example `docker run --rm -v "$PWD/client/static/js:/js:ro" alpine sh -c 'apk add -q nodejs && node --check /js/system_logs.js'`.
- Design sample pages (Artifacts) cannot load a Font Awesome stylesheet (CSP). Use inline SVG, or load the FA 6.4 JS build from cdnjs.
- Stylesheets are cached by the browser, so a fix that "does nothing" after deploy may be a stale CSS file. Hard-refresh before concluding it failed.

## 7. Reference implementation checklist

When building a similar settings modal, match the Log settings modal:

- collapsible rows with a one-line summary, icon, name, chevron
- sticky Expand all bar (divider and tint only when scrolled)
- round pause button and switch driven by one size variable
- Custom pause: For / Until tabs, live clock, 24h fields, clamped to device bounds
- shared popover menu for choices (pause durations, min level pills)
- master switch off: frosted veil plus inert content
- locked rows: lock on the ball, read-only dependent field

## 8. Pre-flight checklist (run before showing or shipping any UI)

Go through every line. Each one exists because it was corrected once.

**Stability**
- [ ] Toggle every state (on, off, paused, locked, read-only, error, loading). Does any control move? Does any row, card or modal change height? If yes, fix it before showing.
- [ ] Do tabs or modes of one panel have the same height and the same field positions (labels on both, or on neither)?
- [ ] Does a long value (long name, long date) truncate with an ellipsis instead of wrapping or pushing a control?
- [ ] Is data still visible in every state? A status may be added to a line, never replace the values already on it.

**Sizing**
- [ ] Controls that belong together (a button beside a switch, a field beside a field) come from one variable, not two numbers.
- [ ] Row of fields: widths fit the content, not the full width. Heights equal.
- [ ] Phone width (about 400px): no horizontal scroll, no clipped text, touch targets slightly larger but not oversized.

**Time and animation**
- [ ] Glyphs that live on a moving part (the switch ball) appear after it stops and vanish immediately when it leaves.
- [ ] No transition on `all` inside anything that toggles `visibility` or `opacity` (inherited visibility fades and looks like overlap).
- [ ] Time is 24-hour, dates are `YYYY-MM-DD`, seconds only where a live clock needs them.

**Input**
- [ ] A value outside the allowed range cannot be reached: pickers are bounded, a committed value is clamped, the primary action is disabled meanwhile.
- [ ] The limits come from the device or API, not from a guess. The message states the real range.
- [ ] Linked inputs (For / Until) stay in sync live and show each other's value.
- [ ] Choice lists use the shared popover menu, never a native `<select>`. Keep native number spinners.

**State meaning**
- [ ] Each state has exactly one visual language (paused = amber, locked = lock glyph, off = faded and inert). No second icon saying the same thing.
- [ ] Disabled things stay visible and readable. A section shut by a master switch is veiled and `inert`, with one short message.
- [ ] Locked / read-only items show why (a lock), not only that they are inactive.

**Style**
- [ ] No extra borders, shadows or tints. Contrast only appears when it carries meaning, and it lands on the label or control, not the whole band.
- [ ] Hairlines are the project's `--nk-border`; separators inside menus are lighter still.
- [ ] Colors come from existing tokens (`--nk-*`, `--sl-*`); literal colors only for a new semantic one (paused amber). Never a custom property defined in terms of itself.
- [ ] Copy is terse and has no stack traces. A status line is one short phrase.

**Process**
- [ ] Samples were shown first and the user picked. Project files were changed only after "نفّذ".
- [ ] Nothing was removed that the user did not ask to remove. Where the request was ambiguous, the interpretation is stated in the reply.
- [ ] JS was syntax-checked (see section 6). The reply says what was and was not verified, and that deploying (`@web_update`) is the user's step.

## 9. Corrections already made (do not repeat)

A log of what was fixed on the Log settings redesign, as the pattern behind each rule above.

| What went wrong | The rule it created |
|---|---|
| Gap above the sticky bar showed rows scrolling behind it | Scroll body has no top padding; the bar owns its padding and is full-bleed |
| Whole sticky band was tinted | Contrast lands on the label/control only, very light, only when scrolled |
| Divider under the bar always visible | Dividers that mark scrolling appear only while scrolled |
| Controls moved when "Paused until" appeared | Controls pinned to the title line, one summary line, no wrapping |
| Row height changed on pause | Status lives in the single summary line; it truncates, it does not wrap |
| Values vanished when a status replaced them | A status is added to a line; it never removes the data |
| Pause button bigger than the switch | One size variable drives both |
| Pause icon on the ball appeared mid-slide | Icon fades in after the ball settles |
| A play icon beside/inside the switch | Paused is shown once; resume only through the switch |
| Switch invisible when off | Off still has a ring; never define a token as itself |
| Min level was a native select | Shared popover menu with log-level pills |
| Number spinners removed | Keep native spinners |
| Fields stretched full width | Fixed, content-sized widths |
| Custom pause modal changed height between tabs | Both tabs share one grid cell; hide with a class, not `hidden` |
| Tab content overlapped for a moment | No `transition: all` inside the switched container |
| Until field sat higher than the For fields | Same label row above both |
| 12-hour AM/PM and locale date | 24-hour fields and a `YYYY-MM-DD` read-only field |
| Error message showed the wrong limit | Limits read from the device bounds; message states the real range |
| Past times could be typed | Bounded pickers and clamping, action disabled while invalid |
| Tabs did not show each other's value | Live sync and cross-display (`Until ...` / `For ...`) |
| Lock icon removed when only an addition was requested | Add means add; never remove unasked |
| Chips offered values over the limit | Options that exceed a limit are disabled or hidden |
