"""REQ-ENG-10 (part): the side states' bodies. A question or an answer may run over several lines (line feeds and
tabs) but holds no other control character; a reason is one line; lengths as the notes' CHECK allows."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from bridge.engagements.schemas import AnswerInfoBody, PauseBody, RequestInfoBody, ResumeBody


@pytest.mark.parametrize("body", [RequestInfoBody, AnswerInfoBody])
def test_a_question_or_an_answer_keeps_line_feeds_and_tabs_only(body: type[RequestInfoBody | AnswerInfoBody]) -> None:
    field = "question" if body is RequestInfoBody else "answer"
    body.model_validate({"lock_version": 0, field: "Which depots?\n\t- Nairobi\n\t- Mombasa"})
    body.model_validate({"lock_version": 0, field: "x" * 2000})
    for wrong in ("Carriage\rreturn", "Bell\x07", "Escape\x1b[31m", "Null\x00", "Delete\x7f", "", "x" * 2001):
        with pytest.raises(ValidationError):
            body.model_validate({"lock_version": 0, field: wrong})


def test_a_reason_is_one_line() -> None:
    PauseBody.model_validate({"lock_version": 0, "reason": "Budget cycle", "resume_at": date(2026, 10, 20)})
    ResumeBody.model_validate({"lock_version": 0, "reason": "x" * 500})
    for wrong in ("Two\nlines", "Tab\there", "x" * 501, ""):
        with pytest.raises(ValidationError):
            ResumeBody.model_validate({"lock_version": 0, "reason": wrong})
        with pytest.raises(ValidationError):
            PauseBody.model_validate({"lock_version": 0, "reason": wrong, "resume_at": date(2026, 10, 20)})
