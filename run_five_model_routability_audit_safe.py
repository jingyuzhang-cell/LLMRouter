#!/usr/bin/env python3
"""Compatibility runner for objective-v2.2's empty post-marker line bug."""

import build_five_model_routability_audit as audit


_frozen_objective_score = audit.objective_score


def safe_objective_score(task: dict, response: str):
    # A terminal marker has an empty substring whose splitlines() is [].
    # Adding a newline makes it [''] without changing any scorable content.
    return _frozen_objective_score(task, response + "\n")


audit.objective_score = safe_objective_score
audit.main()
