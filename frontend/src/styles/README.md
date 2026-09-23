# Frontend styles

`../styles.css` is the ordered entry point for the application stylesheet. Its
imports preserve the cascade from the former single file. Keep that order when
editing existing rules: several later sections intentionally override earlier
selectors, including shared chat and workspace controls.

Put a new rule in the file for the feature that owns it. Use `foundation.css`
for tokens and document defaults, and `app-shell.css` for the sidebar and main
frame. The other filenames follow their page or feature. `VoiceStudio.css` and
`PodcastLibrary.css` remain page-level imports in their React pages.

When moving rules between files, check the final import order and the built CSS;
moving a rule can change specificity ties even if its selector is unchanged.
