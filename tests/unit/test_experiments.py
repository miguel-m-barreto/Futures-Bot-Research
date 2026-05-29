from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.experiments import Cohort, Experiment
from futures_bot.domain.ids import CohortId, ExperimentId


def test_valid_experiment_and_cohort_creation() -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    experiment = Experiment(
        experiment_id=ExperimentId("experiment-1"),
        name="Baseline comparison",
        description="Compare foundation bot cohorts.",
        created_at=created_at,
    )
    cohort = Cohort(
        cohort_id=CohortId("cohort-1"),
        experiment_id=experiment.experiment_id,
        name="USDT candidates",
        description="Paper-only candidates.",
        created_at=created_at,
    )

    assert cohort.experiment_id == experiment.experiment_id


def test_empty_name_rejected() -> None:
    with pytest.raises(ValidationError, match="name"):
        Experiment(
            experiment_id=ExperimentId("experiment-1"),
            name="",
            description="No name.",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Cohort(
            cohort_id=CohortId("cohort-1"),
            experiment_id=ExperimentId("experiment-1"),
            name="Candidates",
            description="No naive timestamps.",
            created_at=datetime(2026, 1, 1),
        )
