# Copyright 2016 Mycroft AI, Inc.
#
# This file is part of Mycroft Core.
#
# Mycroft Core is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Mycroft Core is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Mycroft Core.  If not, see <http://www.gnu.org/licenses/>.

import time
import arrow
import dateutil.parser as dparser
from datetime import datetime, timedelta
from os.path import dirname, join, abspath

from mycroft import MycroftSkill
from mycroft.util import play_mp3
from mycroft.audio import wait_while_speaking
from mycroft.util.log import LOG
from adapt.intent import IntentBuilder


class AlarmSkill(MycroftSkill):

    def __init__(self):
        super(AlarmSkill, self).__init__()
        self.time_format = self.config_core.get('time_format')
        self.should_converse = False
        self.stop_notify = False
        self.allow_notify = False
        self.converse_context = {}

    def initialize(self):
        # self.register_intent_file('set.morning.intent', self.set_morning)
        # self.register_intent_file('set.sunrise.intent', self.set_sunrise)
        # self.register_intent_file('delete.all.intent', self.delete_all)
        # self.register_entity_file('exceptdaytype.entity')

        # using adapt because padatious seems to
        # not pick this up for some reason
        status_intent = IntentBuilder("status.alarm.intent"). \
            require("status").require("alarm").build()
        self.register_intent(status_intent, self.handle_status)

        # using padatious
        self.register_intent_file('delete.intent', self.handle_delete)
        self.register_intent_file('set.recurring.intent',
                                  self.handle_set_recurring)
        self.register_intent_file('stop.intent', self.stop)
        if self.time_format == 'half':
            self.register_intent_file('set.time.intent', self.handle_set_time)
            self.register_entity_file('ampm.entity')
        elif self.time_format == 'full':
            self.register_intent_file('set.time.24hr.intent',
                                      self.handle_set_time)
        self.register_entity_file('time.entity')
        self.register_entity_file('length.entity')
        self.register_entity_file('daytype.entity')

        if self.settings.get("alarms", None) is None:
            self.settings["alarms"] = []
        else:
            self._load_alarms()

    def save_alarm(self, alarm_object):
        """ save alarms to settings """
        self.settings['alarms'].append(alarm_object)

    def remove_alarm(self, alarm_name):
        """ removes alarm from settings """
        # TODO: deal with recurring
        for index, alarm_object in enumerate(self.settings['alarms']):
            if alarm_object["name"] == alarm_name:
                self.settings['alarms'].pop(index)

    def _load_alarms(self):
        """ loads alarms from settings.json and schedules them
            if the alarm time has not yet pass
        """
        for alarm_object in self.settings['alarms']:
            alarm_name = alarm_object['name']
            for i, _alarm_time in enumerate(alarm_object['arrow_objects']):
                now = arrow.now()
                alarm_time = arrow.get(_alarm_time)
                if alarm_time.timestamp > now.timestamp:
                    self._schedule_alarm_event(alarm_name, alarm_time)
                else:
                    alarm_object['arrow_objects'].pop(i)

                if len(alarm_object['arrow_objects']) == 0:
                    self.remove_alarm(alarm_name)

    def parse_message_data(self, message_data):
        """ parses the message from message bus and returns an
            alarm object

            Args:
                message_data (dict): a dictionary from the intent message bus

            return:
                alarm_object (dict): first pass for the alarm data
        """
        daytype = message_data.get('daytype', "").replace(" ", "")
        time = message_data.get('time', "").replace(" ", "")
        length = message_data.get('length', "")
        ampm = message_data.get('ampm', "").replace(" ", "")
        name = None
        recurring = message_data.get('recurring', False)

        # special case for am and pm as padatious sometimes
        # match the ampm entity with extra words
        if ampm != "":
            if 'pm' in ampm.lower() or 'p.m' in ampm.lower() or \
               'evening' in ampm.lower():
                ampm = 'p.m.'
            if 'am' in ampm.lower() or 'a.m' in ampm.lower() or \
               'morning' in ampm.lower():
                ampm = 'a.m.'

        # TODO think about recurring alarms
        recurring_str = "" if recurring is False else "recurring "
        if time != "":
            name = "{}{} {} {}".format(
                recurring_str, time, ampm, daytype)
            name = name.strip()
        elif length is not None:
            name = "{}".format(length)

        # TODO: deal with weekend, weekdays, etc
        _days = ["monday", "tuesday", "wednesday", "thursday",
                 "friday", "saturday", "sunday"]

        if 'weekend' in daytype.lower():
            days = _days[5:7]
        elif 'weekday' in daytype.lower():
            days = _days[0:5]
        elif daytype == "":
            days = [_days[arrow.now().replace(tzinfo='local').weekday()]]
        else:
            days = [_days[i] for i in range(len(_days)) if _days[i] in daytype]

        return {
            "time": time,
            "length": length,
            "daytype": daytype,
            "ampm": ampm,
            "name": name,
            "recurring": recurring,
            "days": days,
            "arrow_objects": []
        }

    def _schedule_alarm_event(self, alarm_name, alarm_time):
        """ schedules the alarm using event scheduler api from MycroftSkill
            calls handle_end_timer as a callback when alarm time is up

            Args:
                alarm_name (str): unique name i.e. 10:30 pm wednesday
                alarm_time (datetime): datetime object of alarm time
        """
        LOG.info("scheduling {} alarm".format(alarm_name))
        self.schedule_event(self.handle_end_timer, alarm_time,
                            data=alarm_name, name=alarm_name)

    def schedule_alarm(self, message_data):
        """ handles scheduling alarm, saving alarm, and
            speak utterance

            Args:
                message_data (dict): a dictionary from the intent message bus
        """
        alarm_object = self.parse_message_data(message_data)

        if alarm_object['length'] != "":
            d = dparser.parse(alarm_object["name"])
            now = datetime.now()
            seconds, minutes, hours = d.second, d.minute, d.hour
            time = now + timedelta(
                hours=hours, minutes=minutes, seconds=seconds)
            self._schedule_alarm_event(alarm_object["name"], time)
            arrow_object = arrow.get(time).replace(tzinfo='local')
            alarm_object['arrow_objects'].append(str(arrow_object))
        else:
            days_to_schedule = alarm_object["days"]
            for i, day in enumerate(days_to_schedule):
                time, ampm = alarm_object['time'], alarm_object['ampm']
                time_string = "{} {} {}".format(time, ampm, day)
                d = dparser.parse(time_string, fuzzy=True)
                arrow_object = arrow.get(d).replace(tzinfo='local')
                time = arrow_object.datetime
                alarm_name = alarm_object["name"] + str(i)
                self._schedule_alarm_event(alarm_name, time)
                alarm_object['arrow_objects'].append(str(arrow_object))

        LOG.info(alarm_object)
        self.save_alarm(alarm_object)
        self.speak_alarm(alarm_object)

    def speak_alarm(self, alarm_object):
        """ speaks the alarm using speak function from MycroftSkill"""
        self.speak("Okay. Setting a {} alarm"
                   .format(alarm_object["name"]))

    def handle_end_timer(self, message):
        """ callback for _schedule_alarm_event scheduled_event()

            Args:
                message (Message): object passed by messagebus
        """
        alarm_name = message.data
        self.cancel_timer(alarm_name)
        self.speak("{} alarm is up".format(alarm_name[:-1]))
        wait_while_speaking()
        self.notify()

        # handle recurring
        recurring = False
        for alarm_object in self.settings['alarms']:
            if alarm_object['name'] == alarm_name[:-1]:
                if alarm_object['recurring'] is True:
                    arrow_objects = alarm_object['arrow_objects']
                    arrow_objects = [arrow.get(arw) for arw in arrow_objects]
                    obj_with_smallest_time_delta = {
                        "arrow_object": None,
                        "index": None,
                        "time": float("inf")
                        }
                    # the time we want to re-schedule
                    # should be the closest time to now
                    now = arrow.now()
                    for i, arw in enumerate(arrow_objects):
                        diff = abs(arw.timestamp - now.timestamp)
                        if diff < obj_with_smallest_time_delta["time"]:
                            obj_with_smallest_time_delta["arrow_object"] = arw
                            obj_with_smallest_time_delta["time"] = diff
                            obj_with_smallest_time_delta["index"] = i

                    arrow_time_to_schedule = \
                        obj_with_smallest_time_delta["arrow_object"]
                    arrow_object = arrow_time_to_schedule.shift(weeks=+1)
                    time = arrow_object.datetime
                    self._schedule_alarm_event(alarm_name, time)
                    index = obj_with_smallest_time_delta["index"]
                    if index is not None:
                        alarm_object['arrow_objects'].pop(index)
                        alarm_object['arrow_objects'].append(str(arrow_object))
                    recurring = True

        if recurring is False:
            self.remove_alarm(alarm_name)

    def cancel_timer(self, timer_name):
        """ cancel timer through event shceduler

            Args:
                timer_name (str): name of timer in event scheduler
        """
        self.cancel_scheduled_event(timer_name)

    def handle_set_time(self, message):
        """ Callback for set time intent. parses the message bus message,
            and handles control flow for differnt cases
        """
        LOG.info(message.data)
        # error handling step to make sure recurring
        # request goes to right intent
        if 'every' in message.data['utterance'] or \
                'recurring' in message.data['utterance']:
            self.handle_set_recurring(message)
            return

        if 'time' in message.data:
            # TODO deal with multiple days ex. set alarm for mon, tues, wed
            if self.time_format == 'half':
                ampm = message.data.get('ampm', None)
                if ampm is None:
                    self.set_converse('need.ampm', message.data)
                    self.speak_dialog('alarm.ampm', expect_response=True)
                    return
            self.schedule_alarm(message.data)
        elif 'length' in message.data:
                self.schedule_alarm(message.data)
        else:
            self.speak_dialog('alarm.error')

    def handle_set_recurring(self, message):
        """ Callback for set recurring time intent. """
        LOG.info(message.data)
        message.data['recurring'] = True
        if 'time' in message.data:
            if self.time_format == 'half':
                ampm = message.data.get('ampm', None)
                if ampm is None:
                    self.set_converse('need.ampm', message.data)
                    self.speak_dialog('alarm.ampm', expect_response=True)
                    return
            self.schedule_alarm(message.data)
        else:
            self.speak_dialog('alarm.error')

    # TODO: speak alarm in chronological order
    def handle_status(self, message):
        """ Callback for status alarm intent """
        LOG.info(message.data)
        if len(self.settings['alarms']) == 0:
            self.speak_dialog('alarm.status')
        else:
            alarms = self.settings['alarms']
            num_of_alarms = len(alarms)
            names = [alarm['name'] for alarm in alarms]
            speak_string = "you have {} active alarms.".format(num_of_alarms)
            for i, name in enumerate(names):
                if (i + 1) == len(names):
                    speak_string += " and {}".format(name)
                else:
                    speak_string += " {}.".format(name)
            self.speak(speak_string)

    def delete_all(self, message):
        pass

    # TODO: converse for multiple alarms
    def handle_delete(self, message):
        """" Callback for delete alarm intent """
        LOG.info(message.data)
        alarm_object = self.parse_message_data(message.data)
        alarm_to_delete = alarm_object['name']
        alarms = self.settings['alarms']

        delete_object = []
        for alarm in alarms:
            alarm_name = alarm['name']
            if alarm_to_delete.lower() in alarm_name.lower():
                delete_object.append(alarm_name)

        if len(delete_object) > 1:
            self.speak("you have {} alarms similar to that. " +
                       "which one are you referring too.")
        elif len(delete_object) == 1:
            self.speak("canceling {} alarm".format(alarm_to_delete))
            self.remove_alarm(delete_object[0])
        else:
            self.speak(
                "I can not find an alarm set for {}".format(alarm_to_delete))

    def notify(self, repeat=6):
        """ recursively calls it's self to play alarm mp3

            Args:
                repeat (int): number of times it'll call itself
        """
        if hasattr(self, 'notify_event_name'):
            self.cancel_scheduled_event(self.notify_event_name)

        self.allow_notify = True
        path = join(abspath(dirname(__file__)), 'timerBeep.mp3')
        self.notify_process = play_mp3(path)
        if self.stop_notify is False:
            if repeat > 0:
                arw_time = arrow.now().replace(tzinfo='local')
                arw_time = arw_time.shift(seconds=4)
                self.notify_event_name = \
                    'mycroftalarm.notify.repeat.{}'.format(repeat)
                self.schedule_event(
                    lambda x=None: self.notify(repeat - 1), arw_time.datetime,
                    data=self.notify_event_name, name=self.notify_event_name)
            else:
                self.reset_notify()
        if self.stop_notify is True:
            self.reset_notify()

    def reset_notify(self):
        self.allow_notify = False
        self.stop_notify = False

    def set_converse(self, context, data):
        self.converse_context = {'context': context, 'data': data}
        self.should_converse = True

    def reset_converse(self):
        self.converse_context = {}
        self.should_converse = False

    def converse(self, utterances, lang='en-us'):
        if self.converse_context['context'] == 'need.ampm':
            utt = utterances[0]
            prev_message_data = self.converse_context.get('data')
            if 'pm' in utt.lower() or 'p.m' in utt.lower() or \
               'evening' in utt.lower():
                prev_message_data["ampm"] = 'p.m.'
            elif 'am' in utt.lower() or 'a.m' in utt.lower() or \
                 'morning' in utt.lower():
                prev_message_data["ampm"] = 'a.m.'
            else:
                self.speak_dialog('alarm.ampm', expect_response=True)
                return self.should_converse
            self.schedule_alarm(prev_message_data)
            self.reset_converse()
            return True

        return self.should_converse

    # TODO: try this on mark 1
    def stop(self):
        if self.allow_notify is True:
            self.stop_notify = True
            self.allow_notify = False
            self.cancel_scheduled_event(self.notify_event_name)
            self.notify_process.kill()


def create_skill():
    return AlarmSkill()
