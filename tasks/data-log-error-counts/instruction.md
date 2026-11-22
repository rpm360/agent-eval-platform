`/workspace/app.log` is an application log. Each line has the format:

```
<ISO timestamp> <LEVEL> [<module>] <message>
```

Count the number of lines whose LEVEL is exactly `ERROR`, grouped by module. Only the LEVEL
field counts — the word "error" appearing inside a message does not.

Write the result to `/workspace/errors.json` as a JSON object mapping module name to count.
Only include modules with at least one ERROR line.
