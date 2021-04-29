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

    #print('\nASKING QUESTION')
    emit_utterance(context.bus, 'cancel all alarms')
    for i in range(10):
        wait_while_speaking()
        for message in context.bus.get_messages('speak'):
            if message.data.get('meta', {}).get('dialog') in followups:
                #print("\nWaiting before saying yes ...")
                time.sleep(2)
                emit_utterance(context.bus, 'yes')
                rc = wait_for_dialog(context.bus, cancelled)
                #print('\nWere we understood--->rc= %s' % (rc,))
                context.bus.clear_messages()
                return
            elif message.data.get('meta', {}).get('dialog') in no_alarms:
                context.bus.clear_messages()
                return
        time.sleep(1)
    context.bus.clear_messages()


@given('an alarm is expired and beeping')
def given_expired_alarm(context):
    got_msg = False
    emit_utterance(context.bus, 'set an alarm for 1 minute from now')

    # drain any existing messages
    for message in context.bus.get_messages('mycroft.alarm.beeping'):
        pass

    ctr = 0
    while ctr < 60 and not got_msg:
        time.sleep(1)

        # wait for msg = beeping
        for message in context.bus.get_messages('mycroft.alarm.beeping'):
            #print("\n\nDETECT BEEPING MSG !!!\n\n")
            got_msg = True

        ctr += 1

    context.bus.clear_messages()
    assert got_msg, "Error, did not get beeping message!"


@then('"mycroft-alarm" should stop beeping')
def then_stop_beeping(context):
    # TODO Implement
    pass


@then('"mycroft-alarm" should stop beeping and start beeping again in 10 minutes')
def then_stop_and_start_beeping(context):
    start_time = time.time()
    got_msg = False

    # drain any existing messages
    for message in context.bus.get_messages('mycroft.alarm.beeping'):
        pass

    ctr = 0
    while ctr < 3 and not got_msg:
        time.sleep(60)

        # wait for msg = beeping
        for message in context.bus.get_messages('mycroft.alarm.beeping'):
            got_msg = True

        ctr += 1

    elapsed = time.time() - start_time
    context.bus.clear_messages()
    #assert got_msg and elapsed > 5*60, "Error, did not get beeping message!"
    assert got_msg, "Error, did not get beeping message!"


@then('"mycroft-alarm" should stop beeping and start beeping again in 5 minutes')
def then_stop_and_start_beeping(context):
    start_time = time.time()
    got_msg = False

    # drain any existing messages
    for message in context.bus.get_messages('mycroft.alarm.beeping'):
        pass

    ctr = 0
    while ctr < 7 and not got_msg:
        time.sleep(60)

        # wait for msg = beeping
        for message in context.bus.get_messages('mycroft.alarm.beeping'):
            got_msg = True

        ctr += 1

    elapsed = time.time() - start_time
    context.bus.clear_messages()
    # TODO assert got msg and > 3 minutes!
    #assert got_msg and elapsed > 3*60, "Error, did not get beeping message!"
    assert got_msg, "Error, did not get beeping message!"


