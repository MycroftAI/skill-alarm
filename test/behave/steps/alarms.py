import time

from behave import given, then

from mycroft.audio import wait_while_speaking
from mycroft.skills.api import SkillApi

from test.integrationtests.voight_kampff import emit_utterance, wait_for_dialog


@given('an alarm is set for {alarm_time}')
def given_set_alarm(context, alarm_time):
    emit_utterance(context.bus, 'set an alarm for {}'.format(alarm_time))
    wait_for_dialog(context.bus, ['alarm.scheduled.for.time'])
    context.bus.clear_messages()


@given('there are no previous alarms set')
def given_no_alarms(context):
    SkillApi.connect_bus(context.bus)
    alarm_skill = SkillApi.get('mycroft-alarm.mycroftai')
    alarm_skill.delete_all_alarms()


@given('an alarm is expired and beeping')
def given_expired_alarm(context):
    emit_utterance(context.bus, 'set an alarm in 10 seconds')
    time.sleep(12)


@then('"mycroft-alarm" should stop beeping')
def then_stop_beeping(context):
    # TODO Implement
    pass
