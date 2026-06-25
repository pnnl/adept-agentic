"""Regression tests for perform_demo.py regex patterns.

These test the job ID extraction and result detection regexes
that parse agent output during multi-turn polling.
"""

import re
import sys
from pathlib import Path

import pytest

# Add demos/ to path so we can import the regex patterns directly
DEMOS_DIR = Path(__file__).resolve().parents[2] / "demos"
sys.path.insert(0, str(DEMOS_DIR))


# --- Job ID extraction regex (from perform_demo.py) ---
# Updated to handle markdown formatting: **Job ID:** `856125`

JOB_ID_PATTERN = re.compile(
    r"(?:job[_ ]?(?:id)?[:\s*`]*|Submitted batch job\s+|slurm-)(\d{5,})",
    re.IGNORECASE,
)


class TestJobIDExtraction:
    """Regression: job IDs must be extracted from all known agent output formats."""

    def test_submitted_batch_job(self):
        text = "Submitted batch job 856076"
        ids = JOB_ID_PATTERN.findall(text)
        assert "856076" in ids

    def test_job_id_colon(self):
        text = "Job ID: 856076"
        ids = JOB_ID_PATTERN.findall(text)
        assert "856076" in ids

    def test_job_id_lowercase(self):
        text = "job id 856076 submitted"
        ids = JOB_ID_PATTERN.findall(text)
        assert "856076" in ids

    def test_slurm_output_filename(self):
        """Regression: agent mentions slurm-XXXXX.out in error messages."""
        text = (
            "head: cannot open '/people/rigo160/adept-workspace/"
            "response_e57ea5987efc430b/slurm-856076.out' for reading"
        )
        ids = JOB_ID_PATTERN.findall(text)
        assert "856076" in ids

    def test_multiple_job_ids(self):
        text = (
            "Submitted batch job 856075\n"
            "Then submitted batch job 856076\n"
            "The output is in slurm-856076.out"
        )
        ids = JOB_ID_PATTERN.findall(text)
        assert "856075" in ids
        assert "856076" in ids

    def test_no_false_positive_on_short_numbers(self):
        """Numbers with fewer than 5 digits should NOT match."""
        text = "Job 1234 is too short"
        ids = JOB_ID_PATTERN.findall(text)
        assert ids == []

    def test_job_underscore_format(self):
        text = "job_id: 123456"
        ids = JOB_ID_PATTERN.findall(text)
        assert "123456" in ids

    def test_markdown_bold_backtick(self):
        """Regression (Session 66): agent returns **Job ID:** `856125`."""
        text = "submitted: - **Job ID:** `856125` - **Cluster:** Deception HPC"
        ids = JOB_ID_PATTERN.findall(text)
        assert "856125" in ids

    def test_markdown_bold_no_backtick(self):
        """Agent may use bold without backtick: **Job ID:** 856125."""
        text = "**Job ID:** 856125"
        ids = JOB_ID_PATTERN.findall(text)
        assert "856125" in ids

    def test_markdown_backtick_only(self):
        """Agent may use backtick without bold: Job ID: `856125`."""
        text = "Job ID: `856125`"
        ids = JOB_ID_PATTERN.findall(text)
        assert "856125" in ids

    def test_full_agent_turn1_output(self):
        """Regression: full Turn 1 output from demo run 2026-06-17."""
        text = (
            "The COBRApy Flux Balance Analysis (FBA) job was successfully "
            "submitted: - **Job ID:** `856125` - **Cluster:** Deception HPC "
            "The job is now running. Please allow some time for it to complete."
        )
        ids = JOB_ID_PATTERN.findall(text)
        assert "856125" in ids
        assert len(ids) == 1


# --- Result detection regex (from perform_demo.py) ---
# Must contain keyword + delimiter + decimal number within 30 chars

RESULT_PATTERN = re.compile(
    r"(?:flux|objective|optimal).{0,30}(?:=|:|is)\s*-?[\d]+\.[\d]+",
    re.IGNORECASE,
)


class TestResultDetection:
    """Regression: result regex must match actual numeric values, not generic text."""

    def test_matches_biomass_flux_value(self):
        text = "The optimal biomass flux value is 0.8739"
        assert RESULT_PATTERN.search(text) is not None

    def test_matches_objective_value_equals(self):
        text = "objective value = 1.234"
        assert RESULT_PATTERN.search(text) is not None

    def test_matches_flux_colon(self):
        text = "flux: 0.8739"
        assert RESULT_PATTERN.search(text) is not None

    def test_matches_optimal_value(self):
        text = "optimal value: 2.5"
        assert RESULT_PATTERN.search(text) is not None

    def test_matches_negative_value(self):
        text = "optimal flux is -0.123"
        assert RESULT_PATTERN.search(text) is not None

    def test_no_false_positive_on_generic_text(self):
        """Generic mentions of 'flux' without numeric context should NOT match."""
        text = (
            "In order to proceed with checking the status of the "
            "FBA (Flux Balance Analysis) job that was submitted"
        )
        assert RESULT_PATTERN.search(text) is None

    def test_no_false_positive_on_narrative_mention(self):
        """Instructional text without an actual number should NOT match."""
        text = "Report the biomass flux value from the output."
        assert RESULT_PATTERN.search(text) is None

    def test_no_match_for_flux_in_sentence(self):
        """'flux balance analysis' without a number should not match."""
        text = "Running flux balance analysis on the model"
        assert RESULT_PATTERN.search(text) is None

    def test_no_false_positive_on_fba_acronym(self):
        """The full phrase 'Flux Balance Analysis' without = or : should not match."""
        text = (
            "In order to proceed with checking the status of the FBA "
            "(Flux Balance Analysis) job"
        )
        assert RESULT_PATTERN.search(text) is None


# --- COMPLETED state detection regexes (from perform_demo.py) ---
# Positive: job state IS completed. Negative: conditional/future mention.

COMPLETED_POSITIVE = re.compile(
    r"(?:state|status|job).{0,40}(?:is|:|=)\s*[\"'`*]*COMPLETED",
    re.IGNORECASE,
)
COMPLETED_NEGATIVE = re.compile(
    r"(?:once|when|until|updates?\s+to|becomes?)\s.{0,20}COMPLETED",
    re.IGNORECASE,
)


def _should_break_completed(text: str) -> bool:
    """Replicate the break logic from perform_demo.py."""
    return bool(COMPLETED_POSITIVE.search(text)) and not bool(
        COMPLETED_NEGATIVE.search(text)
    )


class TestCompletedDetection:
    """Regression (Session 66): premature COMPLETED detection from conditional text."""

    def test_job_status_is_completed(self):
        text = "The job status is COMPLETED with exit code 0."
        assert _should_break_completed(text)

    def test_job_state_completed(self):
        text = 'job_state: "COMPLETED"'
        assert _should_break_completed(text)

    def test_state_equals_completed(self):
        text = "state = COMPLETED"
        assert _should_break_completed(text)

    def test_state_completed_with_markdown(self):
        text = "The job state is **COMPLETED** successfully."
        assert _should_break_completed(text)

    def test_no_false_positive_once_updates_to(self):
        """Regression: Turn 3 said 'Once the status updates to COMPLETED'."""
        text = (
            'The FBA job is still marked as "RUNNING". Once the status '
            'updates to "COMPLETED," I will read the output file.'
        )
        assert not _should_break_completed(text)

    def test_no_false_positive_when_becomes(self):
        text = "When the job becomes COMPLETED, I will read the output."
        assert not _should_break_completed(text)

    def test_no_false_positive_until_completed(self):
        text = "Waiting until the job is COMPLETED before reading output."
        assert not _should_break_completed(text)

    def test_no_false_positive_running_with_completed_mention(self):
        """Full Turn 3 output from demo run 2026-06-17."""
        text = (
            'The FBA job is still marked as "RUNNING" according to the '
            "details retrieved. The job is not yet complete. Once the status "
            'updates to "COMPLETED," I will read the output file and report '
            "the biomass flux value. If you need progress updates at regular "
            "intervals, let me know!"
        )
        assert not _should_break_completed(text)

    def test_no_false_positive_pure_running_report(self):
        """Agent simply reports RUNNING without mentioning COMPLETED at all."""
        text = "The job is currently in RUNNING state on partition short."
        assert not _should_break_completed(text)

    def test_completed_with_sacct_json(self):
        """Agent quoting sacct JSON output."""
        text = 'The sacct query shows job state is "COMPLETED" with exit code 0:0.'
        assert _should_break_completed(text)
