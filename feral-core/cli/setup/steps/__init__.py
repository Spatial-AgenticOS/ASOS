"""Wizard step modules.

Each module exposes ``run(state: WizardState)`` — may be sync or
async. The state machine in :mod:`cli.setup.state_machine` awaits the
coroutine when async.
"""
