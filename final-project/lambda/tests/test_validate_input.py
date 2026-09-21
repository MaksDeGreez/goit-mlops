import json

import pytest

from validate_input import InvalidInputError, build_args, build_job_name, lambda_handler

REPOSITORY = "123456789012.dkr.ecr.us-east-1.amazonaws.com/final-project/training"
GIT_SHA = "039325b1c0a94ad0bdfbbdcd6f2f0f4b0a3b9c11"


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    monkeypatch.setenv("TRAINING_IMAGE_REPOSITORY", REPOSITORY)
    monkeypatch.delenv("JOB_NAME_PREFIX", raising=False)


def call(payload, execution_name="8f1e0a02-0d41-4d27-9f0e-7b6a1f0c1234"):
    return lambda_handler({"input": payload, "execution_name": execution_name}, None)


def test_valid_input_builds_the_image_and_the_job_name():
    result = call({"image_tag": "abc1234", "git_sha": GIT_SHA})

    assert result["image"] == f"{REPOSITORY}:abc1234"
    assert result["image_tag"] == "abc1234"
    assert result["git_sha"] == GIT_SHA
    assert result["job_name"].startswith("training-")
    assert result["args"] == []


def test_the_job_name_is_unique_per_execution():
    first = call({"image_tag": "t", "git_sha": GIT_SHA}, execution_name="run-one")
    second = call({"image_tag": "t", "git_sha": GIT_SHA}, execution_name="run-two")

    assert first["job_name"] != second["job_name"]


def test_a_plain_input_without_the_wrapper_also_works():
    result = lambda_handler(
        {"image_tag": "abc1234", "git_sha": GIT_SHA, "execution_name": "manual-run"}, None
    )

    assert result["job_name"] == "training-manual-run"


def test_the_git_sha_is_lower_cased():
    result = call({"image_tag": "abc1234", "git_sha": GIT_SHA.upper()})

    assert result["git_sha"] == GIT_SHA


def test_the_job_name_prefix_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("JOB_NAME_PREFIX", "train")

    assert call({"image_tag": "t", "git_sha": GIT_SHA})["job_name"].startswith("train-")


@pytest.mark.parametrize(
    "payload",
    [
        {"git_sha": GIT_SHA},
        {"image_tag": "", "git_sha": GIT_SHA},
        {"image_tag": 7, "git_sha": GIT_SHA},
        {"image_tag": "bad tag", "git_sha": GIT_SHA},
        {"image_tag": "-starts-with-a-dash", "git_sha": GIT_SHA},
    ],
)
def test_a_bad_image_tag_is_rejected(payload):
    with pytest.raises(InvalidInputError):
        call(payload)


@pytest.mark.parametrize(
    "git_sha",
    [None, "", "not-hex-at-all", "abc", "unknown", GIT_SHA + "aa"],
)
def test_a_bad_git_sha_is_rejected(git_sha):
    with pytest.raises(InvalidInputError):
        call({"image_tag": "abc1234", "git_sha": git_sha})


def test_a_missing_execution_name_is_rejected():
    with pytest.raises(InvalidInputError):
        lambda_handler({"input": {"image_tag": "t", "git_sha": GIT_SHA}}, None)


def test_a_missing_repository_is_rejected(monkeypatch):
    monkeypatch.setenv("TRAINING_IMAGE_REPOSITORY", "")

    with pytest.raises(InvalidInputError):
        call({"image_tag": "t", "git_sha": GIT_SHA})


def test_the_input_must_be_an_object():
    with pytest.raises(InvalidInputError):
        lambda_handler({"input": "abc1234", "execution_name": "run"}, None)


def test_parameters_become_command_line_arguments():
    result = call(
        {
            "image_tag": "abc1234",
            "git_sha": GIT_SHA,
            "params": {"max_iter": 50, "learning_rate": 0.05, "sample_rows": 500},
        }
    )

    assert result["args"] == [
        "--learning-rate",
        "0.05",
        "--max-iter",
        "50",
        "--sample-rows",
        "500",
    ]


def test_parameters_are_sorted_so_the_output_is_stable():
    args = build_args({"seed": 1, "max_iter": 2, "l2_regularization": 0.0})

    assert args[0::2] == ["--l2-regularization", "--max-iter", "--seed"]


def test_a_text_parameter_is_passed_through():
    assert build_args({"experiment_name": "canary-test"}) == [
        "--experiment-name",
        "canary-test",
    ]


def test_no_parameters_gives_no_arguments():
    assert build_args(None) == []
    assert build_args({}) == []


@pytest.mark.parametrize(
    "params",
    [
        {"unknown_option": 1},
        {"max_iter": "50"},
        {"max_iter": True},
        {"experiment_name": "has spaces"},
        {"experiment_name": "semi;colon"},
        {"experiment_name": 3},
        "not-an-object",
    ],
)
def test_bad_parameters_are_rejected(params):
    with pytest.raises(InvalidInputError):
        build_args(params)


def test_the_job_name_stays_within_the_kubernetes_limit():
    name = build_job_name("training", "a" * 200)

    assert len(name) <= 63
    assert not name.endswith("-")


def test_an_execution_name_without_usable_characters_is_rejected():
    with pytest.raises(InvalidInputError):
        build_job_name("training", "***")


def test_the_result_is_json_serialisable():
    # Step Functions passes the answer on as JSON, so nothing exotic may be in it.
    json.dumps(call({"image_tag": "abc1234", "git_sha": GIT_SHA}))
