## Registering a vault

- Lab file: `registry/<lab>.yml`
- Vault name(s):

Checklist:

- [ ] The origin repository is public and `git clone` works without credentials
- [ ] The vault has an `OWNERS` file at its root
- [ ] The host is not already in `registry/` and is not a reserved name
- [ ] The content license is stated (default CC BY-SA 4.0)
- [ ] `python3 scripts/validate.py --online` passes locally
