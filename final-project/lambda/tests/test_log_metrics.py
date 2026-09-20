import json

import pytest

from log_metrics import (
    TrainingResultNotFoundError,
    find_training_result,
    iter_log_texts,
    lambda_handler,
)

RESULT = {
    "event": "training_finished",
    "model": "california-housing",
    "version": "3",
    "run_id": "a48c01d7c9af4878b08942e9ae876f46",
    "rmse": 0.4453,
    "mae": 0.2947,
    "r2": 0.8486,
    "git_sha": "039325b",
    "dataset_sha256": "41f849ea",
    "model_sha256": "70d8f5f5",
}


def logs(text, pod="training-run-abc123", container="training"):
    """The shape Step Functions returns when RetrieveLogs is turned on."""
    return {"pods": {pod: {"containers": {container: {"log": text}}}}}


def job_output(text):
    return {
        "job_name": "training-run-abc123",
        "image": "registry/final-project/training:abc1234",
        "git_sha": "039325b",
        "job": {"logs": logs(text)},
    }


def test_the_result_line_is_found_between_other_lines():
    text = "\n".join(
        [
            "loading the data",
            "not json at all",
            '{"event": "run_started"}',
            json.dumps(RESULT),
            "",
        ]
    )

    assert find_training_result(logs(text)) == RESULT


def test_the_last_matching_line_wins():
    old = dict(RESULT, version="1")
    text = json.dumps(old) + "\n" + json.dumps(RESULT)

    assert find_training_result(logs(text))["version"] == "3"


def test_log_text_given_directly_as_a_string_also_works():
    plain = {"pods": {"training-run-abc123": {"containers": {"training": json.dumps(RESULT)}}}}

    assert find_training_result(plain) == RESULT


def test_several_containers_are_all_searched():
    several = {
        "pods": {
            "pod-a": {"containers": {"sidecar": {"log": "nothing here"}}},
            "pod-b": {"containers": {"training": {"log": json.dumps(RESULT)}}},
        }
    }

    assert find_training_result(several) == RESULT


@pytest.mark.parametrize(
    "text",
    [
        "",
        "the job crashed",
        '{"event": "run_started"}',
        '{"event": "training_finished"',  # cut off in the middle
        "[1, 2, 3]",
    ],
)
def test_a_missing_result_line_fails_clearly(text):
    with pytest.raises(TrainingResultNotFoundError) as error:
        find_training_result(logs(text))

    assert "training_finished" in str(error.value)


def test_empty_logs_fail_clearly():
    with pytest.raises(TrainingResultNotFoundError):
        find_training_result({})


def test_iter_log_texts_walks_lists_too():
    assert list(iter_log_texts({"a": ["one", {"b": "two"}]})) == ["one", "two"]


def test_the_handler_returns_the_result_and_the_context():
    answer = lambda_handler(job_output(json.dumps(RESULT)), None)

    assert answer["event"] == "training_pipeline_finished"
    assert answer["job_name"] == "training-run-abc123"
    assert answer["git_sha"] == "039325b"
    assert answer["training"] == RESULT


def test_the_handler_also_accepts_the_logs_at_the_top_level():
    answer = lambda_handler({"logs": logs(json.dumps(RESULT))}, None)

    assert answer["training"] == RESULT


def test_the_handler_fails_when_the_job_printed_nothing():
    with pytest.raises(TrainingResultNotFoundError):
        lambda_handler(job_output("segmentation fault"), None)


def test_the_handler_prints_one_json_line(capsys):
    lambda_handler(job_output(json.dumps(RESULT)), None)

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["event"] == "training_metrics"
    assert record["service"] == "log-metrics"
    assert record["rmse"] == RESULT["rmse"]
    assert record["version"] == "3"
    assert "ts" in record and "level" in record


def test_the_answer_is_json_serialisable():
    json.dumps(lambda_handler(job_output(json.dumps(RESULT)), None))
