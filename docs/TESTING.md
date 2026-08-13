# Testing

Run the public test suite with:

```powershell
py -m unittest discover -s tests -v
```

The public repository intentionally omits personal EQ logs and saved Allakhazam HTML regression fixtures, so tests that require those local fixtures skip when the files are absent.
