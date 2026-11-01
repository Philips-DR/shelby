"""With no model set up, notes and minutes say so plainly, first; nothing else in meet-ai is touched by it.

The SDK's own words for this were "No AWS region was provided. Set the `aws_region` argument, ...", which never said
that the real trouble was that no model had been set up at all."""

import pytest

from meetnotes.client import ANTHROPIC, BEDROCK, ModelConfig, NoModel, check_configured
from meetnotes.operations import OperationError, generate_minutes, generate_notes


def test_an_api_key_in_the_config_or_the_environment_is_a_model():
    check_configured(ModelConfig(provider=ANTHROPIC, api_key="k"), env={})
    check_configured(ModelConfig(provider=ANTHROPIC), env={"ANTHROPIC_API_KEY": "k"})
    check_configured(ModelConfig(provider=ANTHROPIC), env={"ANTHROPIC_AUTH_TOKEN": "t"})


def test_a_region_is_what_makes_bedrock_a_model():
    check_configured(ModelConfig(provider=BEDROCK, region="us-east-1"), env={})
    check_configured(ModelConfig(provider=BEDROCK), env={"AWS_DEFAULT_REGION": "us-east-1"})


@pytest.mark.parametrize("config", [ModelConfig(provider=ANTHROPIC), ModelConfig(provider=BEDROCK)])
def test_nothing_to_call_is_said_in_plain_words(config):
    with pytest.raises(NoModel) as raised:
        check_configured(config, "minutes", env={})
    message = str(raised.value)
    assert message.startswith("No model is set up, so minutes cannot be written.")
    assert "ANTHROPIC_API_KEY" in message and "do not need a model" in message


@pytest.mark.parametrize("operation,what", [(generate_notes, "notes"), (generate_minutes, "minutes")])
def test_notes_and_minutes_say_so_before_they_look_for_a_transcript(operation, what, tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(name, raising=False)
    # the timeline does not exist: if the transcript were read first, this would be about that instead
    with pytest.raises(OperationError) as raised:
        operation(tmp_path / "nothing.timeline.json", ModelConfig(provider=BEDROCK))
    assert f"No model is set up, so {what} cannot be written" in str(raised.value)


# ---- a model call that fails because of how the model is set up ---------------------------------------------------------


def named(name, message="x"):
    return type(name, (Exception,), {})(message)


@pytest.mark.parametrize("provider,error,says", [
    (ANTHROPIC, named("AuthenticationError", "401"), "The Anthropic API key was refused, so notes cannot be written"),
    (ANTHROPIC, named("PermissionDeniedError", "403"), "key was refused"),
    (ANTHROPIC, named("NotFoundError", "404"), "is not available to this API key"),
    (BEDROCK, named("NoCredentialsError", "Unable to locate credentials"), "No model is set up"),
    (BEDROCK, Exception("Error when retrieving token from sso: Token has expired and refresh failed"), "login has expired"),
    (ANTHROPIC, named("APIConnectionError", "Connection error."), "Could not reach the model"),
])
def test_a_failure_of_the_models_setup_is_said_in_plain_words(provider, error, says):
    from meetnotes.client import explain_model_error
    message = explain_model_error(error, ModelConfig(provider=provider), "notes")
    assert message and says in message


def test_any_other_failure_is_left_as_it_was():
    from meetnotes.client import explain_model_error
    assert explain_model_error(ValueError("a bug"), ModelConfig(provider=ANTHROPIC), "notes") is None


@pytest.mark.parametrize("operation,module_function,what", [
    (generate_notes, "extract_notes", "notes"), (generate_minutes, "extract_minutes", "minutes"),
])
def test_a_refused_key_reaches_the_caller_as_a_plain_error_not_a_bare_exception(operation, module_function, what, tmp_path, monkeypatch):
    import json
    import meetnotes.extract as extract

    timeline = tmp_path / "t.timeline.json"
    timeline.write_text(json.dumps({"version": 1, "segments": [{"start": 0.0, "end": 2.0, "text": "Hello there."}]}))

    def refused(*args, **kwargs):
        raise named("AuthenticationError", "401 invalid x-api-key")

    monkeypatch.setattr(extract, module_function, refused)
    with pytest.raises(OperationError) as raised:
        operation(timeline, ModelConfig(provider=ANTHROPIC, api_key="sk-ant-x"))
    assert f"The Anthropic API key was refused, so {what} cannot be written" in str(raised.value)
