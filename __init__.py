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


# TODO: use dialog instead of speak for localization
class AlarmSkill(MycroftSkill):

    def __init__(self):
        super(AlarmSkill, self).__init__()
        self.time_zone = self.location['timezone']['code']
        self.sound_file = join(abspath(dirname(__file__)), 'timerBeep.wav')

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
            seconds_to_shift = int(self.location['timezone']['offset']) / -1000
            return arrow.get(dt).shift(seconds=seconds_to_shift)

    def _play_beep(self):
        """Plays alarm sound file"""
        play_wav(self.sound_file)

    def _parse_and_append(self, utterance, append):
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
        LOG.info(self._parse_and_append(utterance, append))
        date = extract_datetime(
            self._parse_and_append(utterance, append),
            arrow.now().to(self.time_zone).datetime
        )[0]
        LOG.info(date)
        return self._adjusted_date(date).datetime

    @intent_file_handler('set.time.intent')
    def handle_set_alarm(self, message):
        LOG.info(message.data)
        utterance = message.data.get('utterance')
        length = message.data.get('length')
        time = message.data.get('time')
        now = datetime.now()
        LOG.info(now)
        if length:
            date = extract_datetime(utterance)[0]
            seconds, minutes, hours = date.second, date.minute, date.hour
            time = now + timedelta(
                hours=hours, minutes=minutes, seconds=seconds
            )
            LOG.info(time)
            self.schedule_event(self._play_beep, time)
        elif time:
            if message.data.get('ampm'):
                date = self._extract_datetime(utterance)
                LOG.info(date)
                # self.schedule_event(self._play_beep, date)
            else:
                response = self.get_response('need.ampm')
                am_set = set(self.translate_list('am'))
                pm_set = set(self.translate_list('pm'))
                response_set = set([r.lower() for r in response.split()])
                if am_set & response_set:
                    date = self._extract_datetime(utterance, ' am')
                    LOG.info(date)
                    # self.schedule_event(self._play_beep, date)
                elif pm_set & response_set:
                    date = self._extract_datetime(utterance, ' pm')
                    LOG.info(date)
                    # self.schedule_event(self._play_beep, date)
        else:
            self.speak_dialog('no.time.found')

    def _determine_frequency(self, utterance):
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

    @intent_file_handler('set.recurring.intent')
    def handle_set_recurring(self, message):
        LOG.info(message.data)
        utterance = message.data.get('utterance')
        time = message.data.get('time')
        if time:
            if message.data.get('ampm'):
                date = self._extract_datetime(utterance)
                LOG.info(date)
            else:
                response = self.get_response('need.ampm')
                am_set = set(self.translate_list('am'))
                pm_set = set(self.translate_list('pm'))
                response_set = set([r.lower() for r in response.split()])
                if am_set & response_set:
                    date = self._extract_datetime(utterance, ' am')
                    frequency = self._determine_frequency(utterance)
                    LOG.info(date)
                    LOG.info(frequency)
                elif pm_set & response_set:
                    date = self._extract_datetime(utterance, ' pm')
                    frequency = self._determine_frequency(utterance)
                    LOG.info(date)
                    LOG.info(frequency)
        else:
            self.speak_dialog('no.time.found')

    @intent_file_handler('alarm.status.intent')
    def handle_status(self, message):
        LOG.info('sttufff')
        pass

    @intent_file_handler('delete.intent')
    def handle_delete(self, message):
        pass

    @intent_file_handler('stop.intent')
    def handle_stop(self, message):
        pass


def create_skill():
    return AlarmSkill()
