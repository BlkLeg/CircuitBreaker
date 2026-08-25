# Internationalization — Take the Selector Down — Design

**Date:** 2026-08-24
**Status:** Approved design, not yet implemented
**Branch context:** `dev` at `de9ff24c`; `VERSION` = `1.0.0-rc.3`
**Register:** Batch D — INC-09.

**Standing policy for 1.0.0:** *when a surface promises more than the build delivers, remove
the scaffolding and state the boundary.* This batch is that policy applied literally.

## 1. Problem

### 1.1 The register's numbers are wrong, and the correction changes the decision

INC-09 states: *"There are 227 distinct `t('…')` call sites in the app; only three components
call `useTranslation` at all... Everything else renders its `defaultValue`."*

Those two claims cannot both be true. A `t()` call in a component that never called
`useTranslation` is a `ReferenceError`, not a `defaultValue` fallback.

The app contains **two** `t()` call sites in total:

```jsx
components/MacOSDOCK.jsx:122   label={t(item.labelKey, { defaultValue: item.label })}
pages/SettingsPage.jsx:611     label={t('language', { ns: 'settings', defaultValue: 'Language' })}
```

Verified exhaustively: no `<Trans>` component, no `i18n.t()`, no `withTranslation` anywhere
in `src/`. `pages/OOBEWizardPage.jsx:31` imports `useTranslation` and never calls `t`.

Every other user-facing string in the application is a hardcoded literal. The 227 appears to
be a loose grep — the same pattern matches `expect(`, `parseInt(`, and `.at(`, and a naive
count returns over a thousand.

### 1.2 What is actually translated

Roughly twenty-two strings: eighteen `header.*` labels, three `map.*` labels, and
`settings.language`.

| Namespace | English content |
|---|---|
| `common.json` | 543 bytes — `header.*` (15 labels), `map.*` (3 labels) |
| `settings.json` | 29 bytes — `language` |
| `header.json` | `{}` |
| `map.json` | `{}` |
| `hardware.json` | `{}` |

`i18n.js:12` declares namespaces `['common', 'header', 'map', 'settings', 'hardware']`, and
the `header.*` and `map.*` keys live inside `common.json` while the `header` and `map`
namespaces those names imply are empty files.

The non-English content is also incomplete relative to English: `es/common.json` has fifteen
header labels to English's eighteen, missing `certificates`, `notifications`, `tenants`, and
`users`. Switching to Spanish today produces a partly-Spanish dock.

`en/common.json` still ships a `header.tenants` label for a feature ADR-0003 removed.

### 1.3 What the selector promises

`i18n.js:11` advertises `['en', 'es', 'fr', 'de', 'zh', 'ja']` and `pages/SettingsPage.jsx:611-617`
renders a Language selector wired to `i18n.changeLanguage`. Choosing 日本語 changes about
fifteen words in the dock and leaves the entire application in English.

### 1.4 Why this is not a wiring job

Making the selector honest means internationalizing an application that is not
internationalized: extracting every user-facing literal across every page and component into
keys, then sourcing and maintaining six languages. That is a project with its own timeline,
not a 1.0.0 batch. This design takes the claim down and leaves the ground clean for it.

## 2. Decisions

1. Both Language selectors — Settings and the OOBE wizard — are removed. §3.1.
   The persisted `language` field stays; only the six-language claim in the update
   schema is narrowed. §3.1.1.
2. `supportedLngs` narrows to `['en']` and the five non-English locale directories are
   deleted. §3.2.
3. The empty namespaces are deleted and the namespace mismatch is corrected. §3.3.
4. i18next, `I18nextProvider`, and the `labelKey` structure **stay**. §3.4.
5. The boundary is stated in the docs. §5.

## 3. Architecture

### 3.1 Remove both selectors

There are **two**, not one. The register mentions only the Settings control.

- `pages/SettingsPage.jsx:611-617` — the Language `<select>` offering six languages, inside
  the Regional section. It goes, along with `i18n.changeLanguage` at line 399-400 and the
  `t`/`i18n` destructuring at line 248. The one `t()` call in the file is this control's own
  label, so `useTranslation` goes with it.
- `pages/OOBEWizardPage.jsx` — a full **"Preferred Language"** onboarding step: the
  `languages` list (line 148), the state (line 78), the control (lines 1797-1806), the review
  summary line (lines 2161-2162), the field in the setup payload (lines 563, 600), and
  `i18n.changeLanguage(language)` at line 654. All of it goes; `useTranslation` with it.

A new operator currently picks a language during onboarding, sees it echoed in the setup
summary, and gets an English application. That is the worst instance of this finding and the
register does not record it.

### 3.1.1 The `language` setting stays; the claim does not

`language` is not a dead field. It is persisted on both `AppSettings` (`db/models.py:1346`)
and `User` (`db/models.py:1945`), and it is threaded through
`api/bootstrap.py:67`, `services/user_service.py:276`, `services/auth_service.py:257,501,709,846`,
`api/admin_users.py:189,261`, and `api/auth.py:233`.

So this batch does **not** remove it. Ripping a field out of user creation, bootstrap, and
the auth service is a large refactor with no user-visible benefit, and the later i18n project
needs exactly this plumbing.

What is false is not the field but the **claim attached to it**:

```python
# schemas/settings.py:400 — the update schema
language: Literal["en", "es", "fr", "de", "zh", "ja"] | None = None
```

That advertises five languages the build cannot deliver. It narrows to `Literal["en"]`. The
read schema (`schemas/settings.py:129`) keeps returning the stored value, the columns stay,
and every code path above is untouched.

This is the same distinction Batch B draws for INC-18, in the opposite direction:
`show_experimental_features` is removed because nothing reads it, while `language` is kept
because a great deal does. The rule is not "delete unused fields" — it is "stop advertising
what the build cannot do".

**An install that already stored a non-English language** keeps that value in the database
and gets an English UI, because no frontend surface reads it any more. It is not migrated:
the value is a real preference that the i18n project will honour, and destroying it to tidy
a column would lose information for no gain.

### 3.2 One language

`i18n.js`:

```js
supportedLngs: ['en'],
```

`public/locales/{es,fr,de,zh,ja}/` are deleted — five directories of partial translations for
a selector that no longer exists. They are recoverable from git history if the later project
wants them as a starting point, and keeping them would mean shipping content nothing can
reach.

`LanguageDetector` stays in the chain. With one supported language it resolves to `en`
always, and removing it would be a second change to make when the real project starts. It
costs nothing to leave configured correctly.

### 3.3 One namespace, correctly named

The three empty namespace files (`header.json`, `map.json`, `hardware.json`) are deleted and
`i18n.js:12` narrows to:

```js
ns: ['common', 'settings'],
defaultNS: 'common',
```

This resolves the mismatch in §1.2 in the direction the working code already assumes:
`MacOSDOCK.jsx` reads `header.*` keys out of the **default** namespace, which is `common`,
and that is why it works today despite `header.json` being empty. Deleting the empty files
makes the structure describe what happens.

`settings.json` is kept even though §3.1 removes its only consumer. It is one file holding
one key, and the alternative — deleting it and reinstating it — churns for nothing. If the
key is genuinely unused after §3.1, delete it with the namespace and narrow `ns` to
`['common']`; the implementation confirms which and does one or the other, not both.

`en/common.json` drops `header.tenants` (ADR-0003) and gains the four labels the navigation
rework added but `common.json` never received — `certificates`, `notifications`, `users`, and
the Batch A additions — because `__tests__/nav-coverage.test.js`'s *one destination, one name*
suite asserts that any `labelKey` present in `common.json` matches its nav label. A key that
is absent is skipped by that test; a key that is present and wrong fails it. Adding them is
what puts them under the guard.

### 3.4 What stays, and why

i18next, `react-i18next`, `I18nextProvider` (`App.jsx:5`), `i18next-http-backend`, and every
`labelKey` in `data/navigation.js` are retained.

The navigation rework built `labelKey` deliberately, and `nav-coverage.test.js` uses it to
assert that the dock tooltip and the route menu give a destination the same name — the
drift that shipped "External Nodes" in the menu as "External" in the dock. Removing the
i18n layer would remove that guard and turn a later i18n project into a from-scratch
re-introduction rather than a continuation.

The cost of keeping it is one provider and two small locale files. The alternative —
ripping out i18next and rewriting the call sites — is a larger change that destroys
structure, in service of a runtime saving nobody has asked for.

## 4. Testing

- `nav-coverage.test.js`'s *one destination, one name* suite is the existing guard and must
  stay green; §3.3 adds keys, which brings more labels under it rather than fewer.
- A new assertion in that file: `i18n.js`'s `supportedLngs` matches the directories present
  under `public/locales/`. The finding underneath INC-09 is a configuration advertising
  content that does not exist, and this is that made into a test — it fails if a language is
  advertised without a directory, or a directory ships without being advertised.
- `settings-page.test.jsx` loses its Language-selector assertions if it has any, and gains
  one that the control is absent, so the selector cannot return without a decision.

## 5. Documentation

`docs/` states the boundary in one place: **Circuit Breaker 1.0.0 ships in English.** The
i18n scaffolding is present and the interface strings are structured for translation, but no
translated content is shipped and no language selection is offered.

Stating this is the point of the batch. A user who finds `i18next` in the bundle and expects
a language setting should find the answer in the documentation rather than in a selector that
changes fifteen words.

## 6. Files touched

**Frontend:** `i18n.js`, `pages/SettingsPage.jsx`, `pages/OOBEWizardPage.jsx`,
`public/locales/en/common.json`, `public/locales/{es,fr,de,zh,ja}/` (deleted),
`public/locales/en/{header,map,hardware}.json` (deleted),
`__tests__/nav-coverage.test.js`, `__tests__/settings-page.test.jsx`,
`__tests__/oobe-wizard.test.jsx`.

**Backend:** `schemas/settings.py:400` only — the update `Literal` narrows to `["en"]`.
No other backend file changes; see §3.1.1.

**Docs:** `docs/1.0.0-incomplete-features.md` (INC-09 closed, with the call-site correction
recorded), and the English-only statement.

## 7. Out of scope

- **Actually internationalizing the application.** Its own project: string extraction across
  the frontend, a translation-sourcing process, and a drift guard for untranslated keys. This
  design leaves i18next configured and the `labelKey` structure intact so that project starts
  from a clean base rather than from scratch.
- **Backend-originated strings.** API error messages, audit action names, and notification
  bodies are English and are not part of the frontend i18n layer. They would be in scope for
  the real project and are not in scope here.
- **Locale-dependent formatting.** Dates, numbers, and byte sizes are formatted independently
  of i18next and are unaffected.
