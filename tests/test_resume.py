from datetime import date

import pytest
from pydantic import ValidationError

from extraction_engine.samples import RESUME_EMAIL, RESUME_ROLES, RESUME_STATED_YEARS
from extraction_engine.schemas.resume import CandidateResume, WorkExperience, measure_tenure


def _history() -> list[dict[str, object]]:
    return [
        {
            "employer": role.employer,
            "title": role.title,
            "start_date": role.start,
            "end_date": role.end,
            "highlights": [role.highlight],
        }
        for role in RESUME_ROLES
    ]


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "full_name": "Priya Raman",
        "email": f"Priya <{RESUME_EMAIL}>",
        "phone": "415-555-0148",
        "skills": ["Python", " python ", "SQL"],
        "work_history": _history(),
        "years_experience": 5,
    }
    payload.update(overrides)
    return payload


def test_email_is_normalized_and_skills_are_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("extraction_engine.schemas.resume.current_date", lambda: date(2026, 10, 5))
    resume = CandidateResume.model_validate(_payload())
    assert resume.email == RESUME_EMAIL
    assert resume.skills == ["Python", "SQL"]
    assert resume.work_history[0].end_date is None


def test_truncated_email_is_rejected() -> None:
    with pytest.raises(ValidationError, match="not a valid address"):
        CandidateResume.model_validate(_payload(email="priya.raman@", years_experience=5))


def test_end_date_before_start_is_rejected() -> None:
    with pytest.raises(ValidationError, match="end_date"):
        WorkExperience.model_validate(
            {
                "employer": "Harbor Clinic",
                "title": "Data Analyst",
                "start_date": "2023-02-01",
                "end_date": "June 2021",
            }
        )


def test_stated_years_fail_when_they_disagree_with_the_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = date(2026, 10, 5)
    monkeypatch.setattr("extraction_engine.schemas.resume.current_date", lambda: frozen)
    history = [
        WorkExperience.model_validate(
            {
                "employer": role.employer,
                "title": role.title,
                "start_date": role.start,
                "end_date": role.end,
            }
        )
        for role in RESUME_ROLES
    ]
    span = measure_tenure(history, frozen).years
    assert abs(RESUME_STATED_YEARS - span) > 1
    with pytest.raises(ValidationError, match=f"Set years_experience to {span}"):
        CandidateResume.model_validate(_payload(years_experience=RESUME_STATED_YEARS))
    accepted = CandidateResume.model_validate(_payload(years_experience=f"{span}+"))
    assert accepted.years_experience == span
    CandidateResume.model_validate(_payload(years_experience=span + 1))


def test_years_validator_runs_after_work_history() -> None:
    names = list(CandidateResume.model_fields)
    assert names.index("work_history") < names.index("years_experience")
    role_fields = list(WorkExperience.model_fields)
    assert role_fields.index("start_date") < role_fields.index("end_date")
