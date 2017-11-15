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
        self.alarm_on = False
        self.max_delay = self.config['max_delay']
        self.repeat_time = self.config['repeat_time']
        self.extended_delay = self.config['extended_delay']
        self.file_path = join(dirname(__file__), self.config['filename'])
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
            self.register_intent_file('set.time.intent', self.set_time)
            self.register_entity_file('ampm.entity')
        elif self.time_format == 'full':
            self.register_intent_file('set.time.24hr.intent', self.set_time)
        self.register_entity_file('time.entity')
        self.register_entity_file('length.entity')
        self.register_entity_file('daytype.entity')

        if self.settings.get("alarms", None) is None:
            self.settings["alarms"] = []

    def parse_message_data(self, message_data):
        daytype = message_data.get("daytype", "").replace(" ", "")
        time = message_data.get("time", "").replace(" ", "")
        length = message_data.get("length", "")
        ampm = message_data.get("ampm", "").replace(" ", "")

        name = None

        # TODO think about recurring alarms
        if time != "":
            name = "{} {} {}".format(time, ampm, daytype)
        elif length != "":
            name = "{}".format(length)

        return {
            "time": time,
            "length": length,
            "daytype": daytype,
            "ampm": ampm,
            "name": name,
        }

    def create_alarm_object(self, message_data):
        alarm_object = self.parse_message_data(message_data)
        LOG.info(alarm_object)
        d = dparser.parse(alarm_object['name'], fuzzy=True)

        # handle length entity
        if alarm_object['length'] != "":
            now = datetime.now()
            seconds = d.second
            minutes = d.minute
            hours = d.hour
            d = now + timedelta(hours=hours, minutes=minutes, seconds=seconds)

        arrow_object = arrow.get(d).replace(tzinfo='local')
        alarm_object['arrow_object'] = arrow_object
        return alarm_object

    def _schedule_alarm_event(self, alarm_object):
        LOG.info("scheduling alarm")
        # TODO: check to see if alarm already exist
        alarm_time = alarm_object['arrow_object'].datetime
        alarm_name = alarm_object['name']
        self.schedule_event(self.handle_end_timer, alarm_time,
                            data=alarm_name, name=alarm_name)

    def schedule_alarm(self, message_data):
        alarm_object = self.create_alarm_object(message_data)
        self._schedule_alarm_event(alarm_object)
        self.speak_alarm(alarm_object)

    def speak_alarm(self, alarm_object):
        self.speak("Ok. Setting an alarm for {}".format(alarm_object["name"]))

    def handle_end_timer(self, message):
        """ callback for start timer scheduled_event()

            Args:
                message (Message): object passed by messagebus
        """
        alarm_name = message.data
        self.cancel_timer(alarm_name)
        self.speak("{} alarm is up".format(alarm_name))
        wait_while_speaking()
        self.notify()

    def cancel_timer(self, timer_name):
        """ cancel timer through event shceduler

            Args:
                timer_name (str): name of timer in event scheduler
        """
        self.cancel_scheduled_event(timer_name)

    def set_time(self, message):
        LOG.info(message.data)
        if 'time' in message.data:
            if self.time_format == 'half':
                ampm = message.data.get('ampm', None)
                if ampm is None:
                    self.converse_context = {'context': 'need.ampm',
                                             'data': message.data}
                    self.should_converse = True
                    self.speak('No problem. Shall I set it for A.M. or P.M.?',
                               expect_response=True)
                    return
                else:
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

    @staticmethod
    def notify(repeat=3):
        path = join(abspath(dirname(__file__)), 'timerBeep.mp3')
        play_mp3(path)

    def reset_converse(self):
        self.should_converse = False
        self.converse_context = {}

    def converse(self, utterances, lang='en-us'):
        if self.converse_context['context'] == 'need.ampm':
            utt = utterances[0]
            prev_message_data = self.converse_context.get('data')
            if 'pm' in utt.lower() or 'p.m.' in utt.lower():
                prev_message_data["ampm"] = 'pm'
            elif 'am' in utt.lower() or 'a.m.' in utt.lower():
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
