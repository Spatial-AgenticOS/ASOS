# feral-reminders

Starter GenUI app bundle used by the Wave 2 runtime tests.

- Baseline authored surfaces (`list`, `compose`)
- Typed action contracts (`value_schema_ref`) for create/complete/delete/schedule
- `skill_call` routing to the companion `feral_reminders` skill
- Safe default permissions (`storage`) with reminder-specific UX flows

Install locally:

```bash
cd ASOS/feral-core
python -m cli.main app install ../examples/apps/feral-reminders --unsigned
```
