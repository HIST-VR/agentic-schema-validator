"""Resume schema. Email format and tenure consistency are the retry rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from email_validator import EmailNotValidError, validate_email
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationInfo, field_validator

from extraction_engine.schemas.parsing import parse_end_date, parse_required_date

YEARS_TOLERANCE = 1

StartDate = Annotated[date, BeforeValidator(parse_required_date)]
EndDate = Annotated[date | None, BeforeValidator(parse_end_date)]


def current_date() -> date:
    """Clock for open-ended roles. Tests patch this instead of date.today."""
    return date.today()


def parse_years(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("years_experience must be a whole number of years.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            return int(match.group())
    raise ValueError(
        "years_experience must be a whole number of years, such as 5. Copy the number stated in the source."
    )


@dataclass(frozen=True)
class Tenure:
    years: int
    start: date
    end: date
    today: date


class WorkExperience(BaseModel):
    """One employment stint. An empty end date means the role is current."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    employer: str = Field(min_length=1, description="Company or organization.")
    title: str = Field(min_length=1, description="Role title.")
    start_date: StartDate = Field(description="First day of the role. Use YYYY-MM-DD.")
    end_date: EndDate = Field(
        default=None,
        description="Last day of the role. Null when the candidate is still in the role.",
    )
    highlights: list[str] = Field(
        default_factory=list,
        description="Short bullets from the source. Empty when none are stated.",
    )

    @field_validator("end_date")
    @classmethod
    def end_not_before_start(cls, value: date | None, info: ValidationInfo) -> date | None:
        start = info.data.get("start_date")
        if value is not None and isinstance(start, date) and value < start:
            raise ValueError(
                f"end_date {value.isoformat()} is before start_date {start.isoformat()}. "
                "Swap the dates if they were reversed, or use null when the role is current."
            )
        return value

    @field_validator("highlights")
    @classmethod
    def clean_highlights(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


def measure_tenure(history: list[WorkExperience], today: date) -> Tenure:
    start = min(job.start_date for job in history)
    end = max(job.end_date or today for job in history)
    if end < start:
        years = 0
    else:
        years = (end - start).days // 365
    return Tenure(years=years, start=start, end=end, today=today)


class CandidateResume(BaseModel):
    """A candidate profile with a real email and tenure that matches the jobs.

    `work_history` is declared before `years_experience` so the validator can
    read the jobs that have already been checked.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    full_name: str = Field(min_length=2, description="Candidate name.")
    email: str = Field(description="Mailbox address, such as ada@example.com.")
    phone: str | None = Field(default=None, description="Phone number. Null if unstated.")
    location: str | None = Field(default=None, description="City or region. Null if unstated.")
    summary: str | None = Field(default=None, description="Short profile summary. Null if unstated.")
    skills: list[str] = Field(
        min_length=1,
        description="Atomic skill names, one per item. Do not return a sentence.",
    )
    work_history: list[WorkExperience] = Field(
        min_length=1,
        description="Employment stints. Omit roles the source says to exclude.",
    )
    years_experience: Annotated[int, BeforeValidator(parse_years)] = Field(
        ge=0,
        le=80,
        description=(
            "Years of experience as stated on the form or headline. "
            "Copy that stated number. Do not recalculate it from the jobs."
        ),
    )

    @field_validator("email")
    @classmethod
    def email_must_be_formatted(cls, value: str) -> str:
        text = value.strip()
        bracket = re.search(r"<([^<>]+)>", text)
        if bracket:
            text = bracket.group(1).strip()
        try:
            info = validate_email(text, check_deliverability=False)
        except EmailNotValidError as exc:
            raise ValueError(
                f"email {text!r} is not a valid address ({exc}). "
                "Return one mailbox like name@domain.com with no display name."
            ) from exc
        return info.normalized

    @field_validator("skills")
    @classmethod
    def skills_are_names(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            skill = item.strip()
            if not skill:
                continue
            if len(skill) > 48:
                raise ValueError(
                    f"Skill {skill!r} is too long to be one skill name. "
                    "Split prose into short names such as Python, SQL, or dbt."
                )
            key = skill.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(skill)
        if not cleaned:
            raise ValueError("skills must contain at least one skill name, such as Python or SQL.")
        return cleaned

    @field_validator("years_experience")
    @classmethod
    def years_match_history(cls, value: int, info: ValidationInfo) -> int:
        raw_history = info.data.get("work_history")
        if not raw_history:
            return value
        history = [job for job in raw_history if isinstance(job, WorkExperience)]
        if len(history) != len(raw_history) or not history:
            return value
        tenure = measure_tenure(history, current_date())
        if abs(value - tenure.years) > YEARS_TOLERANCE:
            raise ValueError(
                f"years_experience is {value}, but the work history spans {tenure.years} calendar years "
                f"from {tenure.start.isoformat()} to {tenure.end.isoformat()} "
                f"(open roles are counted through {tenure.today.isoformat()}). "
                f"The allowed gap is {YEARS_TOLERANCE} year. Set years_experience to {tenure.years}."
            )
        return value

    def acceptance_summary(self) -> list[str]:
        tenure = measure_tenure(self.work_history, current_date())
        return [
            f"Email {self.email} passed format checks.",
            (
                f"Work history spans {tenure.years} calendar years "
                f"({tenure.start.isoformat()} to {tenure.end.isoformat()}). "
                f"years_experience is {self.years_experience}."
            ),
            f"{len(self.skills)} skills and {len(self.work_history)} roles.",
        ]
