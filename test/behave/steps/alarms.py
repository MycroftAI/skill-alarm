import time

from behave import given, then

from mycroft.messagebus.message import Message
from mycroft.skills.api import SkillApi
from test.integrationtests.voight_kampff import (
    emit_utterance,
    VoightKampffDialogMatcher,
)

CANCEL_RESPONSES = (
    "cancelled-multiple",
    "cancelled-single",
    "cancelled-single-recurring",
    "no-active-alarms",
)


@given("an alarm is set for {alarm_time}")
def given_set_alarm(context, alarm_time):
    emit_utterance(context.bus, "set an alarm for {}".format(alarm_time))
    dialog_matcher = VoightKampffDialogMatcher(context, ["alarm-scheduled"])
    dialog_matcher.match()
    time.sleep(1)
    context.bus.clear_messages()


@given("no active alarms")
def reset_alarms(context):
    """Cancel all active timers to test how skill behaves when no timers are set."""
    time.sleep(2)
    _cancel_all_alarms(context)


def _cancel_all_alarms(context):
    """Cancel all active alarms.

    If one of the expected responses is not spoken, cause the step to error out.
    """
    emit_utterance(context.bus, "cancel all alarms")
    dialog_matcher = VoightKampffDialogMatcher(context, CANCEL_RESPONSES)
    match_found, error_message = dialog_matcher.match()
    assert match_found, error_message


@given("an alarm is expired and beeping")
def given_expired_alarm(context):
    emit_utterance(context.bus, "set an alarm in 10 seconds")
    time.sleep(12)


@then('"mycroft-alarm" should stop beeping')
def then_stop_beeping(context):
    time.sleep(2)
    response = context.bus.wait_for_response(Message("skill.alarm.query-expired"))
    if response and response.data.get("expired_alarms"):
        assert not response.data["expired_alarms"]
