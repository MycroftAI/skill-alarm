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
import dateutil.parser as dparser
import arrow
from datetime import datetime, timedelta
from os.path import dirname, join, abspath

from mycroft import MycroftSkill
from mycroft.util import play_mp3
from mycroft.audio import wait_while_speaking

from mycroft.util.log import LOG


class AlarmSkill(MycroftSkill):

    def __init__(self):
        super(AlarmSkill, self).__init__()
        self.time_format = self.config_core.get('time_format')
        self.should_converse = False
        self.converse_context = {}

    def initialize(self):
        # self.register_intent_file('stop.intent', self.__handle_stop)
        # self.register_intent_file('set.morning.intent', self.set_morning)
        # self.register_intent_file('set.sunrise.intent', self.set_sunrise)
        # self.register_intent_file('set.recurring.intent', self.set_recurring)
        # self.register_intent_file('stop.intent', self.stop)
        # self.register_intent_file('delete.all.intent', self.delete_all)
        # self.register_intent_file('delete.intent', self.delete)
        # self.register_entity_file('exceptdaytype.entity')
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
        # alarm = (alarm_object['name'], str(alarm_object['arrow_object']))
        _alarm_object = alarm_object.copy()
        for i in range(len(alarm_object['arrow_objects'])):
            alarm_object['arrow_objects'][i] = str(alarm_object['arrow_objects'][i])
        self.settings['alarms'].append(_alarm_object)

    def remove_alarm(self, alarm_name):
        """ removes alarm from settings """
        # TODO: deal with recurring
        for index, alarm_object in enumerate(self.settings['alarms']):
            if alarm_object["name"] == alarm_name:
                self.settings['alarms'].pop(index)
        # for index, alarms in enumerate(self.settings['alarms']):
        #     if alarms[0] == alarm_name:
        #         self.settings['alarms'].pop(index)

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

    def create_arrow_objects(self, datetime, alarm_object):
        """ creates and arrow object from datetime passed, and data
            from the alarm_object

            Args:
                datetime (datetime): datetime object
                alarm_object (dict): alarm data
        """
        arrow_objects = []
        arrow_object = arrow.get(datetime).replace(tzinfo='local')
        if alarm_object.get('weekends') is not None:
            for i in range(5, 7):
                arrow_objects.append(arrow_object.shift(weekday=i))
        elif alarm_object.get('weekdays') is not None:
            for i in range(0, 5):
                arrow_objects.append(arrow_object.shift(weekday=i))
        else:
            arrow_objects.append(arrow_object)

        return arrow_objects

    def parse_message_data(self, message_data):
        """ parses message data from intent to create a first pass
            of the alarm object

            Args:
                message_data (dict): a dictionary from the intent message bus

            return:
                alarm_object (dict): first pass for the alarm data
        """
        daytype = message_data.get('daytype', "").replace(" ", "")
        time = message_data.get('time', "").replace(" ", "")
        length = message_data.get('length', "").replace(" ", "")
        ampm = message_data.get('ampm', "").replace(" ", "")
        name = None
        recurring = False

        # special case for am and pm as padatious sometimes
        # match the ampm entity with extra words
        if ampm != "":
            if 'pm' in ampm.lower() or 'p.m' in ampm.lower():
                ampm = 'p.m.'
            if 'am' in ampm.lower() or 'a.m' in ampm.lower():
                ampm = 'a.m.'

        # TODO think about recurring alarms
        recurring_str = "" if recurring is False else "recurring"
        if time != "":
            name = "{} {}{} {}".format(
                recurring_str, time, ampm, daytype)
        elif length is not None:
            name = "{}".format(length)

        # TODO: deal with weekend, weekdays, etc
        # _days = ["monday", "tuesday", "wednesday", "thursday",
        #          "friday", "saturday", "sunday"]

        # if 'weekend' in daytype.lower():
        #     days = _days[5:7]
        # elif 'weekday' in daytype.lower():
        #     days = _days[0:5]
        # elif daytype is None:
        #     days = [arrow.now().replace(tzinfo='local').weekday()]
        # else:
        #     days = [_days[i] for i in range(_days) if _days[i] in daytype]

        return {
            "time": time,
            "length": length,
            "daytype": daytype,
            "ampm": ampm,
            "name": name,
            "recurring": recurring
            # "days": days
        }

    def create_alarm_object(self, message_data):
        """ Create an alarm dict with machine readable data

            Args:
                message_data (dict): a dictionary from the intent message bus

            return:
                alarm_object (dict): an extended alarm data with arrow object
        """
        alarm_object = self.parse_message_data(message_data)
        LOG.info(alarm_object)
        d = dparser.parse(alarm_object['name'], fuzzy=True)
        # d = 
        # handle length entity
        if alarm_object['length'] != "":
            now = datetime.now()
            seconds = d.second
            minutes = d.minute
            hours = d.hour
            d = now + timedelta(hours=hours, minutes=minutes, seconds=seconds)

        # arrow_object = arrow.get(d).replace(tzinfo='local')
        # #arrow_objects = self.create_multiple_arrow_objects(arrow_object, alarm_object)
        arrow_objects = self.create_arrow_objects(d, alarm_object)
        alarm_object['arrow_objects'] = arrow_objects
        return alarm_object

    def _schedule_alarm_event(self, alarm_name, alarm_time):
        """ schedules the alarm using event scheduler api from MycroftSkill
            calls handle_end_timer as a callback when alarm time is up

            Args:
                alarm_name (str): unique name i.e. 10:30 pm wednesday
                alarm_time (datetime): datetime object of alarm time
        """
        LOG.info("scheduling alarm")
        self.schedule_event(self.handle_end_timer, alarm_time,
                            data=alarm_name, name=alarm_name)

    def schedule_alarm(self, message_data):
        """ handles scheduling alarm, saving alarm, and
            speak utterance

            Args:
                message_data (dict): a dictionary from the intent message bus
        """
        alarm_object = self.create_alarm_object(message_data)
        LOG.info(alarm_object)

        # TODO: handle scheduling multiple alarms
        # for i in len(alarm_objects)
        arrow_objects = alarm_object['arrow_objects']
        for i in range(len(arrow_objects)):
            alarm_time = arrow_objects[i].datetime
            if i > 0:
                alarm_name = alarm_object['name'] + str(i)
            else:
                alarm_name = alarm_object['name']
            self._schedule_alarm_event(alarm_name, alarm_time)
        
        # alarm_time = alarm_object['arrow_objects'].datetime
        # alarm_name = alarm_object['name']

        # self._schedule_alarm_event(alarm_name, alarm_time)
        self.save_alarm(alarm_object)

        self.speak_alarm(alarm_object)

    def speak_alarm(self, alarm_object):
        """ speaks the alarm using speak function from MycroftSkill"""
        self.speak("Ok. Setting an alarm for {}".format(alarm_object["name"]))

    def handle_end_timer(self, message):
        """ callback for _schedule_alarm_event scheduled_event()

            Args:
                message (Message): object passed by messagebus
        """
        alarm_name = message.data
        self.cancel_timer(alarm_name)
        self.speak("{} alarm is up".format(alarm_name))
        wait_while_speaking()
        self.notify()
        # TODO: how to handle recurrent
        self.remove_alarm(alarm_name)

    def cancel_timer(self, timer_name):
        """ cancel timer through event shceduler

            Args:
                timer_name (str): name of timer in event scheduler
        """
        self.cancel_scheduled_event(timer_name)

    def handle_set_time(self, message):
        """ Callback for set time event. parses the message bus message,
            and handles control flow for differnt cases
        """
        LOG.info(message.data)
        if 'time' in message.data:
            # daytype = message.data.get('daytype', None)
            # if daytype is not None:
            #     if 'weekend' in daytype.lower():
            #         message.data['weekend'] = True
            #     elif 'weekday' in daytype.lower():
            #         message.data['weekday'] = True

            # TODO deal with multiple days ex. set alarm for mon, tues, wed

            if self.time_format == 'half':
                ampm = message.data.get('ampm', None)
                if ampm is None:
                    self.set_converse('need.ampm', message.data)
                    self.speak('No problem. Shall I set it for A.M. or P.M.?',
                               expect_response=True)
                    return

            self.schedule_alarm(message.data)

        elif 'length' in message.data:
                self.schedule_alarm(message.data)

    def set_morning(self, message):
        pass

    def set_sunrise(self, message):
        pass

    def set_recurring(self, message):
        pass

    def delete_all(self, message):
        pass

    def delete(self, message):
        pass

    # TODO: notify non stop until someone press
    # stop button or tell mycroft stop
    @staticmethod
    def notify():
        path = join(abspath(dirname(__file__)), 'timerBeep.mp3')
        play_mp3(path)

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
            if 'pm' in utt.lower() or 'p.m' in utt.lower():
                prev_message_data["ampm"] = 'pm'
            elif 'am' in utt.lower() or 'a.m' in utt.lower():
                prev_message_data["ampm"] = 'am'
            else:
                self.speak(
                    "Sorry I did not get that, did you mean A.M. or P.M.?",
                    expect_response=True)
                return self.should_converse
            self.schedule_alarm(prev_message_data)
            self.reset_converse()
            return True

        return self.should_converse

    def stop(self):
        pass


def create_skill():
    return AlarmSkill()
