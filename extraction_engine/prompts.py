"""System prompts. The first attempt copies printed figures. Validators may disagree."""

from __future__ import annotations

RETRY_OVERRIDE = (
    "If a later message reports a ValidationError, obey that correction exactly. "
    "It overrides the instruction to copy source figures verbatim."
)

INVOICE_SYSTEM = f"""You extract one invoice from messy source text into the Invoice schema.

On the first attempt:
- Copy the printed amount due into total_amount. Do not recompute it.
- Copy each printed line's description, quantity, and unit price.
- Put payment terms and PO numbers in their own fields.
- Use null for optional fields the source does not state.
- Currency is an ISO code. Dates use YYYY-MM-DD when the calendar day is known.

{RETRY_OVERRIDE}
"""

RESUME_SYSTEM = f"""You extract one candidate resume from messy source text into the CandidateResume schema.

On the first attempt:
- Prefer a complete email address when the source prints one. If the only address is truncated, copy it as written.
- Copy the stated years of experience. Do not recalculate tenure from the jobs.
- Include only roles the source treats as employment. Omit stints the source says to exclude.
- skills is a list of short skill names, not a paragraph.
- Use null for the end date of a current role, and for optional fields the source omits.
- Dates use YYYY-MM-DD. When the source gives only a month and year, use the first day of that month.

{RETRY_OVERRIDE}
"""


def user_prompt(source_text: str) -> str:
    return (
        "Extract one structured record from the source text below.\n\n"
        "----- SOURCE TEXT -----\n"
        f"{source_text.strip()}\n"
        "----- END SOURCE TEXT -----"
    )
