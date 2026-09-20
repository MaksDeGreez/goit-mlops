"""The promotion rules: promote, archive, rollback, sync, delete."""

from __future__ import annotations

import pytest
from tests.conftest import MODEL

from registry_ops.actions import (
    ActionError,
    delete,
    list_versions,
    previous_production_version,
    production_version,
    promote,
    rollback,
    sync,
)
from registry_ops.registry import (
    ARCHIVED_STAGE,
    PRODUCTION_STAGE,
    STAGING_ALIAS,
    STAGING_STAGE,
    aliases_of_model,
)


def stage_of(client, version: str) -> str:
    return client.get_model_version(MODEL, version).current_stage


def tags_of(client, version: str) -> dict[str, str]:
    return client.get_model_version(MODEL, version).tags


def test_the_first_promotion_sets_the_alias_the_stage_and_the_tags(client, settings):
    lines = promote(client, settings, "1")

    assert [line["action"] for line in lines] == ["promote"]
    assert production_version(client, MODEL) == "1"
    assert stage_of(client, "1") == PRODUCTION_STAGE
    tags = tags_of(client, "1")
    assert tags["promoted_by"] == "maks"
    assert tags["promoted_git_sha"] == "0123abc"
    assert tags["promoted_at"].endswith("Z")


def test_the_first_promotion_has_no_previous_production_version(client, settings):
    (line,) = promote(client, settings, "1")

    assert line["from_stage"] == STAGING_STAGE
    assert line["to_stage"] == PRODUCTION_STAGE
    assert line["previous_production_version"] is None
    assert line["result"] == "success"
    assert line["error"] is None


def test_a_second_promotion_archives_the_version_before_it(client, settings):
    promote(client, settings, "1")
    lines = promote(client, settings, "2")

    assert [line["action"] for line in lines] == ["archive", "promote"]
    assert production_version(client, MODEL) == "2"
    assert previous_production_version(client, MODEL) == "1"
    assert stage_of(client, "1") == ARCHIVED_STAGE
    assert tags_of(client, "1")["archived_at"].endswith("Z")
    assert lines[-1]["previous_production_version"] == "1"


def test_promoting_the_production_version_again_changes_nothing(client, settings):
    promote(client, settings, "1")
    lines = promote(client, settings, "1")

    assert [line["action"] for line in lines] == ["no_change"]
    assert production_version(client, MODEL) == "1"
    assert stage_of(client, "1") == PRODUCTION_STAGE


def test_promotion_never_touches_the_staging_alias(client, settings):
    promote(client, settings, "1")

    assert aliases_of_model(client, MODEL)[STAGING_ALIAS] == "3"


def test_promoting_a_version_that_does_not_exist_is_an_error(client, settings):
    with pytest.raises(ActionError, match="does not exist"):
        promote(client, settings, "99")


def test_promoting_an_archived_version_is_refused(client, settings):
    promote(client, settings, "1")
    promote(client, settings, "2")

    with pytest.raises(ActionError, match="archived"):
        promote(client, settings, "1")


def test_rollback_brings_the_previous_production_version_back(client, settings):
    promote(client, settings, "1")
    promote(client, settings, "2")
    lines = rollback(client, settings)

    assert [line["action"] for line in lines] == ["archive", "rollback"]
    assert production_version(client, MODEL) == "1"
    assert stage_of(client, "1") == PRODUCTION_STAGE
    assert stage_of(client, "2") == ARCHIVED_STAGE
    assert previous_production_version(client, MODEL) == "2"


def test_a_second_rollback_undoes_the_first(client, settings):
    promote(client, settings, "1")
    promote(client, settings, "2")
    rollback(client, settings)
    rollback(client, settings)

    assert production_version(client, MODEL) == "2"
    assert previous_production_version(client, MODEL) == "1"


def test_rollback_can_be_told_which_version_to_go_back_to(client, settings):
    promote(client, settings, "1")
    promote(client, settings, "2")
    promote(client, settings, "3")
    rollback(client, settings, "1")

    assert production_version(client, MODEL) == "1"
    assert previous_production_version(client, MODEL) == "3"


def test_rollback_without_a_previous_production_version_is_an_error(client, settings):
    promote(client, settings, "1")

    with pytest.raises(ActionError, match="no previous-production"):
        rollback(client, settings)


def test_sync_does_nothing_when_the_version_is_already_in_production(client, settings):
    promote(client, settings, "2")
    lines = sync(client, settings, "2")

    assert [line["action"] for line in lines] == ["no_change"]
    assert lines[0]["version"] == "2"
    assert lines[0]["previous_production_version"] is None
    assert production_version(client, MODEL) == "2"


def test_sync_promotes_a_newer_version(client, settings):
    promote(client, settings, "1")
    lines = sync(client, settings, "2")

    assert [line["action"] for line in lines] == ["archive", "promote"]
    assert production_version(client, MODEL) == "2"


def test_sync_rolls_back_when_the_version_is_archived(client, settings):
    """This is what a git revert of a promotion commit looks like."""
    promote(client, settings, "1")
    promote(client, settings, "2")
    lines = sync(client, settings, "1")

    assert [line["action"] for line in lines] == ["archive", "rollback"]
    assert production_version(client, MODEL) == "1"
    assert previous_production_version(client, MODEL) == "2"


def test_sync_of_a_version_that_does_not_exist_is_an_error(client, settings):
    with pytest.raises(ActionError, match="does not exist"):
        sync(client, settings, "42")


def test_the_production_version_cannot_be_deleted(client, settings):
    promote(client, settings, "2")

    with pytest.raises(ActionError, match="in production"):
        delete(client, settings, "2")
    assert client.get_model_version(MODEL, "2") is not None


def test_deleting_an_old_version_removes_it_and_its_aliases(client, settings):
    promote(client, settings, "1")
    promote(client, settings, "2")
    (line,) = delete(client, settings, "1")

    assert line["action"] == "delete"
    assert line["from_stage"] == ARCHIVED_STAGE
    assert line["to_stage"] is None
    left = client.search_model_versions(f"name='{MODEL}'")
    assert sorted(str(version.version) for version in left) == ["2", "3"]
    assert "previous-production" not in aliases_of_model(client, MODEL)


def test_the_list_shows_every_version_with_its_stage_and_aliases(client, settings):
    promote(client, settings, "1")
    rows = list_versions(client, MODEL)

    assert [row["version"] for row in rows] == ["3", "2", "1"]
    assert rows[0]["aliases"] == STAGING_ALIAS
    assert rows[-1]["aliases"] == "production"
    assert rows[-1]["stage"] == PRODUCTION_STAGE
    assert rows[-1]["rmse"] == "0.100000"


def test_the_list_of_an_unknown_model_is_an_error(client):
    with pytest.raises(ActionError, match="no versions"):
        list_versions(client, "not-a-model")
