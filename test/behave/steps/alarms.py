import time

from behave import given, then

from mycroft.audio import wait_while_speaking

from test.integrationtests.voight_kampff import emit_utterance, wait_for_dialog


@given('an alarm is set for {alarm_time}')
def given_set_alarm(context, alarm_time):
    emit_utterance(context.bus, 'set an alarm for {}'.format(alarm_time))
    time.sleep(3)
    wait_for_dialog(context.bus, ['alarm.scheduled.for.time'])
    context.bus.clear_messages()


@given('there are no previous alarms set')
def given_no_alarms(context):
    followups = ['ask.cancel.alarm.plural',
                 'ask.cancel.desc.alarm',
                 'ask.cancel.desc.alarm.recurring']
    no_alarms = ['alarms.list.empty']
    cancelled = ['alarm.cancelled.desc',
                 'alarm.cancelled.desc.recurring',
                 'alarm.cancelled.multi',
                 'alarm.cancelled.recurring']

    print('\nASKING QUESTION')
    emit_utterance(context.bus, 'cancel all alarms')
    for i in range(10):
        wait_while_speaking()
        for message in context.bus.get_messages('speak'):
            if message.data.get('meta', {}).get('dialog') in followups:
                print("\nWaiting before saying yes ...")
                time.sleep(2)
                emit_utterance(context.bus, 'yes')
                rc = wait_for_dialog(context.bus, cancelled)
                print('\nWere we understood--->rc= %s' % (rc,))
                context.bus.clear_messages()
                return
            elif message.data.get('meta', {}).get('dialog') in no_alarms:
                context.bus.clear_messages()
                return
        time.sleep(1)
    context.bus.clear_messages()


@given('an alarm is expired and beeping')
def given_expired_alarm(context):
    emit_utterance(context.bus, 'set an alarm in 30 seconds')
    time.sleep(30)


@then('"mycroft-alarm" should stop beeping')
def then_stop_beeping(context):
    # TODO Implement
    pass
