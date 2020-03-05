import time

from behave import given, then

from mycroft.audio import wait_while_speaking
from mycroft.messagebus import Message


def emit_utterance(bus, utt):
    bus.emit(Message('recognizer_loop:utterance',
                     data={'utterances': [utt],
                           'lang': 'en-us',
                           'session': '',
                           'ident': time.time()},
                     context={'client_name': 'mycroft_listener'}))


def wait_for_dialog(context, dialogs, timeout=10):
    for t in range(timeout):
        for message in context.bus.get_messages('speak'):
            dialog = message.data.get('meta', {}).get('dialog')
            if dialog in dialogs:
                context.bus.clear_messages()
                return
        time.sleep(1)
    context.bus.clear_messages()


@given('an alarm is set for {alarm_time}')
def given_set_alarm(context, alarm_time):
    emit_utterance(context.bus, 'set an alarm for {}'.format(alarm_time))
    for i in range(10):
        for message in context.bus.get_messages('speak'):
            dialog = message.data.get('meta', {}).get('dialog')
            if dialog == 'alarm.scheduled.for.time':
                context.bus.clear_messages()
                return

        time.sleep(1)


@given('there are no previous alarms set')
def given_no_alarms(context):
    followups = ['ask.cancel.alarm.plural',
                 'ask.cancel.desc.alarm',
                 'ask.cancel.desc.alarm.recurring']
    no_alarms = ['alarms.list.empty']
    cancelled = ['alarm.cancelled.desc.dialog',
                 'alarm.cancelled.desc.recurring.dialog',
                 'alarm.cancelled.multi.dialog',
                 'alarm.cancelled.multi.dialog',
                 'alarm.cancelled.recurring.dialog',
                 'alarm.cancelled.recurring.dialog']

    print('ASKING QUESTION')
    emit_utterance(context.bus, 'cancel all alarms')
    for i in range(10):
        for message in context.bus.get_messages('speak'):
            if message.data.get('meta', {}).get('dialog') in followups:
                print('Answering yes!')
                time.sleep(2)
                wait_while_speaking()
                emit_utterance(context.bus, 'yes')
                wait_for_dialog(context, cancelled)
                time.sleep(1)
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
