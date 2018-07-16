# Copyright 2017 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import time
import arrow
from os.path import join, abspath, dirname
from datetime import datetime, timedelta
from pytz import timezone

from mycroft import MycroftSkill
from mycroft.util import extract_datetime, extractnumber, play_wav
from mycroft.util.parse import fuzzy_match
from mycroft.audio import wait_while_speaking
from adapt.intent import IntentBuilder
from mycroft import intent_file_handler
from mycroft.util.log import LOG
from dateutil.parser import parse


# TODO: use dialog instead of speak for localization
class AlarmSkill(MycroftSkill):

    def __init__(self):
        super(AlarmSkill, self).__init__()
        self.time_zone = self.location['timezone']['code']
        self.sound_file = join(abspath(dirname(__file__)), 'timerBeep.wav')
        self.beep_process = None
        self._should_play_beep = True
        self.settings['alarms'] = []
        self.settings['repeat_alarms'] = []

    def initialize(self):
        self.register_entity_file('ampm.entity')
        self.register_entity_file('time.entity')
        self.register_entity_file('length.entity')
        self.register_entity_file('daytype.entity')

    def _adjusted_date(self, dt):
        """Adjust datetime according to users timezone

        Arguments:
            dt (datetime) -- datetime object

        Returns:
            arrow -- arrow object
        """
        user_set_tz = \
            timezone(self.time_zone).localize(datetime.now()).strftime('%Z')
        device_tz = time.tzname
        if user_set_tz in device_tz:
            return arrow.get(dt)
        else:
            # TODO: Fix - Offset does not account for CDT, only CST
            seconds_to_shift = int(self.location['timezone']['offset']) / -1000
            # account for daylight savings
            if 'D' in user_set_tz:
                seconds_to_shift += -3600
            return arrow.get(dt).shift(seconds=seconds_to_shift)

    def _play_beep(self):
        """Plays alarm sound file"""
        # LOG.info("beep beep beep")
        if self._should_play_beep:
            time = datetime.now() + timedelta(seconds=6)
            self.schedule_event(self._play_beep, time)
            self.beep_process = play_wav(self.sound_file)
        else:
            self._should_play_beep = True

    def _notify_non_repeat(self, message):
        """callback for the non repeat scheduled event

        Arguments:
            message (Message): Message Object
        """
        # remove alarms that just went off
        self.settings['alarms'] = [
            i for i in self.settings['alarms']
            if i != message.data
        ]
        self._play_beep()

    def _store_alarm(self, date):
        """saves alarm to object

        Arguments:
            date (tuple): datetime, alarm name
        """
        if self.settings.get('alarms'):
            self.settings['alarms'].append(date)
        else:
            self.settings['alarms'] = []
            self.settings['alarms'].append(date)

    def __schedule_event(self, date, name):
        """wrapper to schedule one time events

        Arguments:
            date (datetime): datetime object
            name (str): alarm
        """
        self.schedule_event(
            self._notify_non_repeat,
            date,
            data=str(date),
            name=name
        )

    def _parse_and_append(self, utterance, append):
        """helper to return a formatted string for extract_datetime

        Arguments:
            utterance (str): initial utterance
            append (str): word to add into string

        Returns:
            (str): extract_datetime formatted string
        """
        utt_list = utterance.split()
        new_list = []
        for i in utt_list:
            if extractnumber(i):
                i += append
            if ":" in i:
                i += append
            new_list.append(i)
        return " ".join(new_list)

    def _extract_datetime(self, utterance, append=""):
        """"Wrapper to extract_datetime. Enhance utterance and
            adjust returned datetime according to user set timezone

        Arguments:
            utterance (str): utterance from message.data

        Keyword Arguments:
            append (str): string to enhance utterance

        Returns:
            (datetime): datetime that's been adjusted for user stimezone
        """
        # LOG.info(self._parse_and_append(utterance, append))
        date = extract_datetime(
            self._parse_and_append(utterance, append),
            arrow.now().to(self.time_zone).datetime
        )[0]
        # LOG.info(date)
        return self._adjusted_date(date).datetime

    def get_alarm_name(self, time, *args):
        """create a name for the alarm

        Arguments:
            time (str): time entity from Message object

        Returns:
            (str)
        """
        speak = time.replace(" ", "") + " "
        for i in args:
            speak += i
            speak += " "
        return speak.strip()

    @intent_file_handler('set.time.intent')
    def handle_set_alarm(self, message):
        # LOG.info(message.data)
        utterance = message.data.get('utterance')
        length = message.data.get('length')
        time = message.data.get('time')
        daytype = message.data.get('daytype') or ""
        now = datetime.now()
        # LOG.info(now)
        if length:
            date = extract_datetime(utterance)[0]
            seconds, minutes, hours = date.second, date.minute, date.hour
            time = now + timedelta(
                hours=hours, minutes=minutes, seconds=seconds
            )
            # LOG.info(time)
            speak = length
            self.__schedule_event(time, speak)
            self.speak_dialog('alarm.scheduled', data=dict(time=speak))
            self._store_alarm((str(date), speak))
        elif time:
            if message.data.get('ampm'):
                date = self._extract_datetime(utterance)
                # LOG.info(date)
                speak = self.get_alarm_name(
                    time, message.data.get('ampm'), daytype)
                self.__schedule_event(date, speak)
                self.speak_dialog(
                    'alarm.scheduled', data=dict(time=speak))
                self._store_alarm((str(date), speak))
            else:
                response = self.get_response('need.ampm')
                if response:
                    am_set = set(self.translate_list('am'))
                    pm_set = set(self.translate_list('pm'))
                    response_set = set([r.lower() for r in response.split()])
                    if am_set & response_set:
                        date = self._extract_datetime(utterance, ' am')
                        # LOG.info(date)
                        speak = self.get_alarm_name(time, 'am', daytype)
                        self.__schedule_event(date, speak)
                    elif pm_set & response_set:
                        date = self._extract_datetime(utterance, ' pm')
                        # LOG.info(date)
                        speak = self.get_alarm_name(time, 'pm', daytype)
                        self.__schedule_event(date, speak)
                else:
                    self.speak_dialog('no.time.found')
                    return
                self.speak_dialog(
                    'alarm.scheduled', data=dict(time=speak))
                self._store_alarm((str(date), speak))
        else:
            self.speak_dialog('no.time.found')

    def _get_frequency(self, utterance):
        """determine weekly or daily freqeuncy

        Arguments:
            utterance (str): utterance for Message object

        Returns:
            (int): 604800 for weekly or 86400 for daily
        """
        threshold = 0.85
        weekly_frequency = 604800
        daily_frequency = 86400

        days_list = self.translate_list('days')
        for day in days_list:
            for word in utterance.split():
                if fuzzy_match(word, day) > threshold:
                    return weekly_frequency

        daily_list = self.translate_list('everyday')
        for synonym in daily_list:
            for word in utterance.split():
                if fuzzy_match(word, synonym) > threshold:
                    return daily_frequency

    def _notify_repeat(self, message):
        """callback for repeat schedule events. Delete past time
            and stores new time in the settings

        Arguments:
            message (Message)
        """
        data = message.data
        new_date = parse(data[0]) + timedelta(seconds=data[1])
        self.settings['repeat_alarms'] = [
            i for i in self.settings['alarms']
            if i != data[0]
        ]
        self.settings['repeat_alarms'].append((str(new_date), data[2]))
        self._play_beep()

    def _store_alarm_repeat(self, date):
        """save repeating alarm objects

        Arguments:
            date (tuple): datettime, alarm name
        """
        if self.settings.get('repeat_alarms'):
            self.settings['repeat_alarms'].append(date)
        else:
            self.settings['repeat_alarms'] = []
            self.settings['repeat_alarms'].append(date)

    def _schedule_repeating_event(self, date, frequency, name):
        """"Wrapper to schedule repeating events

        Arguments:
            date (datetime)
            frequency (int): time in seconds between calls
            name (str): name of alarm
        """
        self.schedule_repeating_event(
            self._notify_repeat,
            date,
            frequency,
            data=(str(date), frequency, name),
            name=name + 'repeat'
        )

    @intent_file_handler('set.recurring.intent')
    def handle_set_recurring(self, message):
        # LOG.info(message.data)
        utterance = message.data.get('utterance')
        time = message.data.get('time')
        daytype = message.data.get('daytype') or ""
        if time:
            if message.data.get('ampm'):
                date = self._extract_datetime(utterance)
                frequency = self._get_frequency(utterance)
                speak = self.get_alarm_name(time, 'pm', daytype)
                self._schedule_repeating_event(date, frequency, speak)
                # LOG.info(date)
            else:
                response = self.get_response('need.ampm')
                if response:
                    am_set = set(self.translate_list('am'))
                    pm_set = set(self.translate_list('pm'))
                    response_set = set([r.lower() for r in response.split()])
                    if am_set & response_set:
                        date = self._extract_datetime(utterance, ' am')
                        frequency = self._get_frequency(utterance)
                        # LOG.info(date)
                        # LOG.info(frequency)
                        speak = self.get_alarm_name(time, 'pm', daytype)
                        self._schedule_repeating_event(date, frequency, speak)
                    elif pm_set & response_set:
                        date = self._extract_datetime(utterance, ' pm')
                        frequency = self._get_frequency(utterance)
                        # LOG.info(date)
                        # LOG.info(frequency)
                        speak = self.get_alarm_name(time, 'pm', daytype)
                        self._schedule_repeating_event(date, frequency, speak)
            self.speak_dialog(
                'alarm.scheduled.repeating', data=dict(time=speak))
            self._store_alarm_repeat((str(date), speak))
        else:
            self.speak_dialog('no.time.found')

    @intent_file_handler('alarm.status.intent')
    def handle_status(self, message):
        alarms = [i[1] for i in self.settings.get('alarms', [])]
        repeating_alarms = [
            i[1] for i in self.settings.get('repeat_alarms', [])
        ]

        amt_total = len(alarms) + len(repeating_alarms)
        self.speak_dialog(
            "alarms.list.amt",
            data={'amount': amt_total}
        )

        if len(alarms) > 0:
            speak_string = ""
            for idx, alarm in enumerate(alarms):
                speak_string += alarm + \
                    "." if idx + 1 == len(alarms) else alarm + ", "
            self.speak_dialog("alarms.list", data={'alarms': speak_string})

        if len(repeating_alarms) > 0:
            speak_string = ""
            for idx, repeat_alarms in enumerate(repeating_alarms):
                speak_string += repeat_alarms + \
                    "." if idx + 1 == len(repeating_alarms) \
                    else repeat_alarms + ", "
            self.speak_dialog(
                "alarms.list.repeat",
                data={'alarms': speak_string}
            )

    def delete_alarm(self, name):
        """deletes one time alarms and cancel scheduled
            and remove alarm from settings

        Arguments:
            name (str): name used to schedule alarm
        """
        # LOG.info(name)
        self.cancel_scheduled_event(name)
        self.settings['alarms'] = [
            i for i in self.settings['alarms']
            if i[1] != name
        ]

    def delete_repeat(self, name):
        """"deletes repeating alarms and cancel scheduled
            and remove alarm from settings

        Arguments:
            name (str): name used to schedule alarm
        """
        self.cancel_scheduled_event(name)
        self.settings['repeat_alarms'] = [
            i for i in self.settings['alarms']
            if i[1] != name.replace("repeat", "")
        ]

    @intent_file_handler('delete.intent')
    def handle_delete(self, message):
        # LOG.info(message.data)
        time = message.data.get('time') or ""
        ampm = message.data.get('ampm') or ""
        daytype = message.data.get('daytype') or ""

        name = self.get_alarm_name(time, ampm, daytype)
        # LOG.info(name)

        best_match = (None, float("-1"))
        for alarm in self.settings.get('alarms'):
            prob = fuzzy_match(name, alarm[1])
            if prob > 0.5 and prob > best_match[1]:
                best_match = (alarm[1], prob)

        best_match_repeat = (None, float("-1"))
        for alarm in self.settings.get('repeat_alarms'):
            prob = fuzzy_match(name, alarm[1])
            if prob > 0.5 and prob > best_match_repeat[1]:
                best_match_repeat = (alarm[1], prob)

        def _delete_one_time(name):
            self.delete_alarm(name)
            self.speak_dialog('delete.alarm', data={'name': name})

        def _delete_repeat(name):
            # all repeat alarms has 'repeat'
            # appended to name in the event scheduler
            self.delete_repeat(name+'repeat')
            self.speak_dialog('delete.alarm.recurring', data={'name': name})

        diff = abs(best_match[1] - best_match_repeat[1])
        # if similar by 10% then ask for one to delete
        if 0.0 <= diff <= 0.1 and best_match[0] and best_match_repeat[0]:
            self.speak_dialog('delete.multimatch')
            self.speak_dialog('delete.match', data={'alarms': best_match[0]})
            self.speak_dialog('delete.match.repeat',
                              data={'alarms': best_match_repeat[0]})
            response = self.get_response('delete.multimatch.response')
            one_time = self.translate_list('one.time')
            recurring = self.translate_list('recurring')
            best_option = (None, float('-inf'), None)

            for option in one_time:
                prob = fuzzy_match(option, response)
                if prob > 0.5 and prob > best_option[1]:
                    best_option = (option, prob, "one time")

            for option in recurring:
                prob = fuzzy_match(option, response)
                if prob > 0.5 and prob > best_option[1]:
                    best_option = (option, prob, "recurring")

            if best_option[2] == "recurring":
                name = best_match_repeat[0]
                _delete_repeat(name)
            elif best_option[2] == "one time":
                name = best_match[0]
                _delete_one_time(name)
            else:
                self.speak_dialog('delete.no.options')
        elif best_match[1] > best_match_repeat[1] and best_match[0]:
            # delete best match
            name = best_match[0]
            _delete_one_time(name)
        elif best_match_repeat[1] > best_match[1] and best_match_repeat[0]:
            # delete best match repeat
            name = best_match_repeat[0]
            _delete_repeat(name)
        else:
            self.speak_dialog('delete.no.match')

    def stop(self):
        if self.beep_process:
            self.beep_process.kill()
            self.beep_process = None
            self._should_play_beep = False


def create_skill():
    return AlarmSkill()
