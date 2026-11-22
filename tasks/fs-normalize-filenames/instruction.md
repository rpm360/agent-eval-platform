Rename every file inside `/workspace/docs/` to snake_case using these exact rules:

1. Lowercase the entire file name (including the extension).
2. In the part before the extension, replace every run of characters that are not `a-z` or
   `0-9` with a single underscore `_`.
3. Strip leading and trailing underscores from the part before the extension.

Files that are already compliant must keep their name. Do not modify file contents, and do
not create or delete any other files.
