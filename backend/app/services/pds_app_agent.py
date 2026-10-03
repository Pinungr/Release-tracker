"""Reviewed application guidance for the conversational PDS agent."""
from __future__ import annotations

import re


APP_GUIDANCE = """PDS application guide:
- Sign in, choose a tenant, and reserve a deployment slot on the weekly board.
- The API rechecks permissions, capacity, holidays, freezes and tenant limits.
- Tenant users can work on changes they scheduled, changes in their tenant group,
  or changes on which they collaborate, subject to date and status protection.
- Release Managers/admins manage deployments; only the Owner manages admins.
- Admin/RM uses Unlock / Restore Lock to manage automatic date locks. A manual
  slot freeze still blocks booking. Do not promise availability: use the tool.
- Administrators can complete/close changes and reopen them through PDS screens.
- Upload supporting documents from the change details screen, subject to current
  permissions, required document categories, and date/status restrictions.
- The global AI Enable switch in Release controls and the group's AI Enable
  switch control assistant access. AI Users provides an override while the
  global switch is enabled. The Owner can validate while globally enabled.
- This assistant can only read data and explain workflows. It cannot perform
  application actions. Live settings and record values must come from tools.
"""


def is_guidance_question(message: str) -> bool:
    """Recognize workflow questions without classifying record facts as guidance."""
    lower = message.lower()
    if re.search(r"\b(available|availability|next|earliest|count|total|status)\b", lower):
        return False
    if re.search(r"\bpds[\s_-]*\d+\b|\b(?:chg|crq)[-_ ]?[a-z0-9]+\b", lower):
        return False
    if re.search(r"\b(today|yesterday|tomorrow|my|our|this|that|these|those)\b", lower):
        return False
    return bool(re.search(
        r"\bhow (?:do|can|to)\b|\bwhere (?:do|can|is)\b|"
        r"\b(?:explain|what are)\b.*\b(?:permissions|roles|workflow|rules)\b",
        lower,
    ))
