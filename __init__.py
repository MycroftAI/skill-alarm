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
from os.path import join, abspath, dirname
from datetime import datetime, timedelta
import os.path
from alsaaudio import Mixer
import re

from adapt.intent import IntentBuilder
from mycroft import MycroftSkill, intent_handler, intent_file_handler
from mycroft.audio import wait_while_speaking
from mycroft.configuration.config import LocalConf, USER_CONFIG
from mycroft.messagebus.message import Message
from mycroft.util import play_wav, play_mp3
from mycroft.util.format import nice_date_time, nice_time, nice_date, join_list
from mycroft.util.log import LOG
from mycroft.util.parse import fuzzy_match, extract_datetime, extract_number
from dateutil.parser import parse
from dateutil.rrule import rrulestr
from mycroft.util.time import (
    to_utc, default_timezone, to_local, now_local, now_utc)

try:
    from mycroft.util.time import to_system
except:
    # Until to_system is included in 18.08.3, define it here too
    from dateutil.tz import gettz, tzlocal
    def to_system(dt):
        """ Convert a datetime to the system's local timezone
        Args:
            dt (datetime): A datetime (if no timezone, assumed to be UTC)
        Returns:
            (datetime): time converted to the local timezone
        """
        tz = tzlocal()
        if dt.tzinfo:
            return dt.astimezone(tz)
        else:
            return dt.replace(tzinfo=gettz("UTC")).astimezone(tz)

# WORKING PHRASES/SEQUENCES:
# Set an alarm
#    for 9
#    no for 9 am
# Set an alarm for tomorrow evening at 8:20
# Set an alarm for monday morning at 8
# create an alarm for monday morning at 8
# snooze
# stop
# turn off the alarm
# create a repeating alarm for tuesdays at 7 am
# Set a recurring alarm
# Set a recurring alarm for weekdays at 7
# snooze for 15 minutes
# set an alarm for 20 seconds from now
# Set an alarm every monday at 7
# "Set a recurring alarm for mondays and wednesdays at 7"
# "Set an alarm for 10 am every weekday"
# TODO: Context - save the alarm found in queries as context
#   When is the next alarm
#   >  7pm tomorrow
#   Cancel it


class AlarmSkill(MycroftSkill):
    
    beep_gap = 15       # seconds between end of a beep and the start of next
                        # must be bigger than the max listening time (10 sec)
        
    default_sound = "constant_beep"
    threshold = 0.7     # Threshold for word fuzzy matching

    def __init__(self):
        super(AlarmSkill, self).__init__()
        self.beep_process = None
        self.settings['max_alarm_secs'] = 10*60  # max time to beep: 10 min
        self.beep_start_time = None
        self.flash_state = 0

        # Seconds of gap between sound repeats.
        # The value name must match an option from the 'sound' value of the
        # settingmeta.json, which also corresponds to the name of an mp3
        # file in the skill's sounds/ folder.  E.g. <skill>/sounds/bell.mp3
        #
        self.sounds = {
            "bell":          5.0,
            "escalate":      32.0,
            "constant_beep": 5.0,
            "beep4":         4.0,
            "chimes":        22.0
        }

        # default sound is 'constant_beep'
        self.settings['sound'] = AlarmSkill.default_sound
        self.settings['start_quiet'] = True
        try:
            self.mixer = Mixer()
        except Exception:
            # Retry instanciating the mixer
            try:
                self.mixer = Mixer()
            except Exception as e:
                self.log.error('Couldn\'t allocate mixer, {}'.format(repr(e)))
                self.mixer = None
        self.saved_volume = None

        # Alarm list format [(timestamp, repeat_rule[, timestamp2]), ...]
        # where:
        #  timestamp is a POSIX timestamp float assumed to
        #       be in the utc timezone.
        #
        #  repeat_rule is for generating the next in a series.  Valid
        #       repeat_rules include None for a one-shot alarm or any other
        #       iCalendar rule from RFC <https://tools.ietf.org/html/rfc5545>.
        #
        #  timestamp2 is optional, for a recently passed alarm at boot or a
        #       running or snoozed alarm.  This is the time that is used for
        #       the repeat.  E.g. your daily alarm is a 24 hours increment
        #       from when it was set, not 24 hours from when it shut off
        #       or was snoozed.
        # NOTE: Using list instead of tuple because of serialization
        self.settings["alarm"] = []

    def dump_alarms(self, tag=""):
        # Useful when debugging
        dump = "\n" + "="*30 + " ALARMS " + tag + " " + "="*30 + "\n"
        dump += "raw = " + str(self.settings["alarm"]) + "\n\n"

        now_ts = to_utc(now_utc()).timestamp()
        dt = datetime.fromtimestamp(now_ts)
        dump += "now = {} ({})\n".format(nice_time(self.get_alarm_local(timestamp=now_ts),
                                                   speech=False, use_ampm=True),
                                         now_ts)
        dump += "      U{} L{}\n".format(to_utc(dt), to_local(dt))
        dump += "\n\n"

        idx = 0
        for alarm in self.settings["alarm"]:
            dt = self.get_alarm_local(alarm)
            dump += "alarm[{}] - {} \n".format(idx, alarm)
            dump += "           Next: {} {}\n".format(nice_time(dt, speech=False, use_ampm=True),
                                                    nice_date(dt, now=now_local()))
            dump += "                 U{} L{}\n".format(dt, to_local(dt))
            if len(alarm) >= 3:
                dtOrig = self.get_alarm_local(timestamp=alarm[2])
                dump += "           Orig: {} {}\n".format(nice_time(dtOrig, speech=False, use_ampm=True),
                                                        nice_date(dtOrig, now=now_local()))
            idx += 1

        dump += "="*75

        self.log.info(dump)

    def initialize(self):
        self.register_entity_file('daytype.entity')  # TODO: Keep?
        self.recurrence_dict = self.translate_namedvalues('recurring')

        # Time is the first value, so this will sort alarms by time
        self.settings["alarm"].sort()

        # This will reschedule alarms which have expired within the last
        # 5 minutes, and cull anything older.
        self._curate_alarms(5*60)

        self._schedule()

        # TODO: Move is_listening into MycroftSkill and reimplement (signal?)
        self.is_currently_listening = False
        self.add_event('recognizer_loop:record_begin', self.on_listen_started)
        self.add_event('recognizer_loop:record_end', self.on_listen_ended)

        # Support query for active alarms from other skills
        self.add_event('private.mycroftai.has_alarm', self.on_has_alarm)

    def on_has_alarm(self, message):
        # Reply to requests for alarm on/off status
        total = len(self.settings["alarm"])
        self.bus.emit(message.response(data={"active_alarms": total}))

    def on_listen_started(self, message):
        self.log.info("on started...")
        self.is_currently_listening = True

    def on_listen_ended(self, message):
        self.log.info("on ended...")
        self.is_currently_listening = False

    def is_listening(self):
        return self.is_currently_listening

    def get_alarm_local(self, alarm=None, timestamp=None):
        if timestamp:
            ts = timestamp
        else:
            ts = alarm[0]
        return datetime.fromtimestamp(ts, default_timezone())

    def set_alarm(self, when, name=None, repeat=None):
        if repeat:
            alarm = self._create_recurring_alarm(when, repeat)
        else:
            alarm = [to_utc(when).timestamp(), ""]
            
        alarm.append(name)

        for existing in self.settings["alarm"]:
            if alarm == existing:
                self.speak_dialog("alarm.already.exists")
                return
            if name and name == existing[2]:
                self.is_currently_listening

        self.settings["alarm"].append(alarm)
        self._schedule()
        return alarm

    def _schedule(self):
        # cancel any existing timed event
        self.cancel_scheduled_event('NextAlarm')
        self._curate_alarms()

        # set timed event for next alarm (if it exists)
        if self.settings["alarm"]:
            dt = self.get_alarm_local(self.settings["alarm"][0])
            self.schedule_event(self._alarm_expired,
                                to_system(dt),
                                name='NextAlarm')

    def _curate_alarms(self, curation_limit=1):
        """[summary]
            curation_limit (int, optional): Seconds past expired at which to
                                            remove the alarm
        """
        alarms = []
        now_ts = to_utc(now_utc()).timestamp()

        for alarm in self.settings["alarm"]:
            # Alarm format == [timestamp, repeat_rule[, orig_alarm_timestamp]]
            if alarm[0] < now_ts:
                if alarm[0] < (now_ts - curation_limit):
                    # skip playing an old alarm
                    if alarm[1]:
                         # resched in future if repeat rule exists
                        alarms.append(self._next_repeat(alarm))
                else:
                    # schedule for right now, with the
                    # third entry as the original base time
                    base = alarm[2] if len(alarm) == 3 else alarm[0]
                    alarms.append([now_ts+1, alarm[1], base])
            else:
                alarms.append(alarm)

        alarms.sort()
        self.settings["alarm"] = alarms

    def _next_repeat(self, alarm):
        # evaluate recurrence to the next instance
        if len(alarm) == 3:
            ref = datetime.fromtimestamp(alarm[1])  # repeat from original time (it was snoozed)
        else:
            ref = datetime.fromtimestamp(alarm[0])

        # Create a repeat rule and get the next alarm occurrance after that
        start=to_utc(ref)
        rr = rrulestr("RRULE:" + alarm[1], dtstart=start)
        now = to_utc(now_utc())
        next = rr.after(now)

        self.log.debug("     Now={}".format(now))
        self.log.debug("Original={}".format(start))
        self.log.debug("    Next={}".format(next))

        return [to_utc(next).timestamp(), alarm[1]]

    def _create_recurring_alarm(self, when, recur):
        # 'recur' is a set of day index strings, e.g. {"3", "4"}
        # convert rule into an iCal rrule
        # TODO: Support more complex alarms, e.g. first monday, monthly, etc
        rule = ""
        abbr = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]
        days = []
        for day in recur:
            days.append(abbr[int(day)])
        if days:
            rule = "FREQ=WEEKLY;INTERVAL=1;BYDAY=" + ",".join(days)
        
        if when and rule:
            when = to_utc(when)
            alarm = [when.timestamp(), rule]

            # Create a repeating rule that starts in the past, enough days
            # back that it encompasses any repeat.
            past = when + timedelta(days=-45)
            rr = rrulestr("RRULE:" + alarm[1], dtstart=past)
            now = to_utc(now_utc())
            # Get the first repeat that happens after right now
            next = rr.after(now)
            return [to_utc(next).timestamp(), alarm[1]]
        else:
            return [None, rule]

    def has_expired_alarm(self):
        # True is an alarm should be 'going off' now.  Snoozed alarms don't
        # count until they are triggered again.
        if not self.settings["alarm"]:
            return False

        now_ts = to_utc(now_utc()).timestamp()
        for alarm in self.settings["alarm"]:
            if alarm[0] <= now_ts:
                return True

        return False

    # Wake me on ... (hard to match with Adapt entities)
    @intent_handler(IntentBuilder("").require("WakeMe").
                    optionally("Recurring").optionally("Recurrence"))
    def handle_wake_me(self, message):
        self.handle_set_alarm(message)

    def _create_day_set(self, phrase):
        recur = set()
        for r in self.recurrence_dict:
            if r in phrase:
                for day in self.recurrence_dict[r].split():
                    recur.add(day)
        return recur

    def _recur_desc(self, recur):
        # Create a textual description of the recur set
        day_list = list(recur)
        day_list.sort()
        days = " ".join(day_list)
        for r in self.recurrence_dict:
            if self.recurrence_dict[r] == days:
                return r  # accept the first perfect match

        # Assemble a long desc, e.g. "Monday and Wednesday"
        day_names = []
        for day in days.split(" "):
            for r in self.recurrence_dict:
                if self.recurrence_dict[r] is day:
                    day_names.append(r)
                    break

        return join_list(day_names, self.translate('and'))

    # Set an alarm for ...
    @intent_handler(IntentBuilder("").optionally("Set").require("Alarm").
                    optionally("Recurring").optionally("Recurrence"))
    def handle_set_alarm(self, message):
        utt = message.data.get('utterance').lower()
        recur = None

        if message.data.get('Recurring'):
            # Just ignoring the 'Recurrence' now, we support more complex stuff
            # recurrence = message.data.get('Recurrence')
            recur = self._create_day_set(utt)
            # TODO: remove days following an "except" in the utt

            while not recur:
                r = self.get_response('query.recurrence', num_retries=1)
                if not r:
                    return
                recur = self._create_day_set(r)

            if self.voc_match(utt, "Except"):
                # TODO: Support exceptions
                self.speak_dialog("no.exceptions.yet")
                return

        # Get the time
        when = extract_datetime(utt)
        utt_no_datetime = None
        if not when == None:
            utt_no_datetime = when[1]
            when = when[0]
            
            
        # Get name from leftover string from extract_datetime
        if utt_no_datetime:
            name = self._get_alarm_name(utt_no_datetime)
        else:
            name = ""
            
        # Will return dt of unmatched string
        today = extract_datetime("today")
        today = today[0]
        
        # Check the time if it's midnight. This is to check if the user
        # said a recurring alarm with only the Day or if the user did 
        # specify to set an alarm on midnight. If it's confirmed that 
        # it's for a day only, then get another response from the user 
        # to clarify what time on that day the recurring alarm is.
        is_midnight = self._check_if_utt_has_midnight(utt,
                                                      when,
                                                      self.threshold)
        
        while (not when or when.time() == today.time()) and not is_midnight:
            r = self.get_response('query.for.when', num_retries=1)
            if not r:
                return
            when_temp = extract_datetime(r)
            if not when_temp == None:
                when_temp = when_temp[0]
                is_midnight = self._check_if_utt_has_midnight(r,
                                                            when_temp,
                                                            self.threshold)
                when = datetime(tzinfo = when.tzinfo,
                                year = when.year,
                                month = when.month,
                                day = when.day,
                                hour = when_temp.hour,
                                minute = when_temp.minute)
            else:
                when = None
        
        # Check if we already have a valid date and time. If not, get another
        # response from the user.
        while (not when or when == today) and not is_midnight:
            # No time given, ask for one
            r = self.get_response('query.for.when', num_retries=1)
            if not r:
                return
            when = extract_datetime(r)
            if not when == None:
                when = when[0]
            is_midnight = self._check_if_utt_has_midnight(r,
                                                          when,
                                                          self.threshold)

        # Verify time
        alarm_time = when
        confirmed_time = False
        while (not when or when == today) and not confirmed_time:
            if recur:
                t = nice_time(alarm_time, use_ampm=True)
                conf = self.ask_yesno('confirm.recurring.alarm',
                                      data={'time': t,
                                            'recurrence': self._recur_desc(recur)})
            else:
                t = nice_date_time(alarm_time, now=today, use_ampm=True)
                conf = self.ask_yesno('confirm.alarm', data={'time': t})
            if not conf:
                return
            if conf == 'yes':
                when = [alarm_time]
                confirmed_time = True
            else:
                # check if a new (corrected) time was given
                when = extract_datetime(conf)
                if not when == None:
                    when = when[0]
                if not when or when == today:
                    # Not a confirmation and no date/time in statement, quit
                    return
                alarm_time = when
                when = None  # reverify

        alarm = None
        if not recur:
            alarm_time_ts = to_utc(alarm_time).timestamp()
            now_ts = now_utc().timestamp()
            if alarm_time_ts > now_ts:
                alarm = self.set_alarm(alarm_time, name)
            else:
                if ('today' in utt) or ('tonight' in utt):
                    self.speak_dialog('alarm.past')
                    return
                else:
                    # Set the alarm to find the next 24 hour time slot
                    while alarm_time_ts < now_ts:
                        alarm_time_ts += 86400.0
                    alarm_time = datetime.utcfromtimestamp(alarm_time_ts)
                    alarm = self.set_alarm(alarm_time, name)
        else:
            alarm = self.set_alarm(alarm_time, name, repeat=recur)

        if not alarm:
            # none set, it was a duplicate
            return
        
        # Don't want to hide the animation
        self.enclosure.deactivate_mouth_events()
        if confirmed_time:
            self.speak_dialog("alarm.scheduled")
        else:
            t = self._describe(alarm)
            reltime = nice_relative_time(self.get_alarm_local(alarm))
            if recur:
                self.speak_dialog("recurring.alarm.scheduled.for.time",
                                  data={"time": t, "rel": reltime})
            else:
                self.speak_dialog("alarm.scheduled.for.time",
                                  data={"time": t, "rel": reltime})

        self._show_alarm_anim(alarm_time)
        self.enclosure.activate_mouth_events()
    
    def _get_alarm_name(self, utt):
        """ Get the alarm name using regex on an utterance
        """
        self.log.debug("Utterance being searched: " + utt)
        rx_file = self.find_resource('name.rx', 'regex')
        if utt and rx_file:
            with open(rx_file) as f:
                for pat in f.read().splitlines():
                    pat = pat.strip()
                    self.log.debug("Regex pattern: " + pat)
                    if pat and pat[0] == "#":
                        continue
                    res = re.search(pat, utt)
                    if res:
                        try:
                            name = res.group("Name").strip()
                            self.log.debug('Regex name extracted: '
                                           + name)
                            if name and len(name.strip()) > 0:
                                return name.lower()
                        except IndexError:
                            pass
        return ''
        
    def _check_if_utt_has_midnight(self, utt, init_time, threshold):
        matched = False
        if init_time.time() == datetime(1970, 1, 1, 0, 0, 0).time():            
            for word in self.translate_list('midnight'):
                matched = self._fuzzy_match(word, utt, threshold)
                if matched:
                    return matched

        return matched
                        

    @property
    def use_24hour(self):
        return self.config_core.get('time_format') == 'full'

    def _while_beeping(self, message):
        # Flash time on the display
        if self.flash_state < 3:
            if self.flash_state == 0:
                alarm_timestamp = message.data["alarm_time"]
                dt = self.get_alarm_local(timestamp=alarm_timestamp)
                self._render_time(dt)
            self.flash_state += 1
        else:
            self.enclosure.mouth_reset()
            self.flash_state = 0

        # Listen for cries of "Stop!!!" between beeps (or over beeps for long
        # audio, which is generally quieter)
        if not self.is_listening():
            still_beeping = self.beep_process and self.beep_process.poll() == None
            beep_duration = self.sounds[self.sound_name]
            if not still_beeping or beep_duration > 10:
                self.log.info("Auto listen...")
                self.bus.emit(Message('mycroft.mic.listen'))

    def _show_alarm_anim(self, dt):
        # Animated confirmation of the alarm
        self.enclosure.mouth_reset()

        self._render_time(dt)
        time.sleep(2)
        self.enclosure.mouth_reset()

        # Show an animation
        # TODO: mouth_display_png() is choking images > 8x8
        #       (likely on the enclosure side)
        for i in range(1, 16):
            png = join(abspath(dirname(__file__)),
                       "anim",
                       "Alarm-"+str(int(i))+"-1.png")
            # self.enclosure.mouth_display_png(png, x=0, y=0, refresh=False,
            #                                  invert=True)
            png = join(abspath(dirname(__file__)),
                       "anim",
                       "Alarm-"+str(int(i))+"-2.png")
            if i < 8:
                self.enclosure.mouth_display_png(png, x=8, y=0, refresh=False,
                                                 invert=True)
            png = join(abspath(dirname(__file__)),
                       "anim",
                       "Alarm-"+str(int(i))+"-3.png")
            self.enclosure.mouth_display_png(png, x=16, y=0, refresh=False,
                                             invert=True)
            png = join(abspath(dirname(__file__)),
                       "anim",
                       "Alarm-"+str(int(i))+"-4.png")
            self.enclosure.mouth_display_png(png, x=24, y=0, refresh=False,
                                             invert=True)

            if i == 4:
                time.sleep(1)
            else:
                time.sleep(0.15)
        self.enclosure.mouth_reset()

    def _render_time(self, datetime):
        # Show the time in numbers "8:00 AM"
        timestr = nice_time(datetime, speech=False, use_ampm=True,
                            use_24hour=self.use_24hour)
        x = 16 - ((len(timestr)*4) // 2)  # centers on display
        if not self.use_24hour:
            x += 1  # account for wider letters P and M, offset by the colon

        # draw on the display
        for ch in timestr:
            if ch == ":":
                png = "colon.png"
                w = 2
            elif ch == " ":
                png = "blank.png"
                w = 2
            elif ch == 'A' or ch == 'P' or ch == 'M':
                png = ch+".png"
                w = 5
            else:
                png = ch+".png"
                w = 4

            png = join(abspath(dirname(__file__)), "anim", png)
            self.enclosure.mouth_display_png(png, x=x, y=2, refresh=False)
            x += w

    def _describe(self, alarm):
        if alarm[1]:
            # Describe repeating alarms
            if alarm[1].startswith("FREQ=WEEKLY;INTERVAL=1;BYDAY="):
                days = alarm[1][29:]  # e.g. "SU,WE"
                days = (days.replace("SU", "0").replace("MO", "1").
                        replace("TU", "2").replace("WE", "3").
                        replace("TH", "4").replace("FR", "5").
                        replace("SA", "6").replace(",", " "))  # now "0 3"
                recur = set()
                for day in days.split():
                    recur.add(day)
                desc = self._recur_desc(recur)
            else:
                desc = self.translate('repeats')

            dt = self.get_alarm_local(alarm)
            
            dialog = 'recurring.alarm'
            if alarm[2]:
                dialog = dialog + '.named'
            return self.translate(dialog,
                                  data={'time': nice_time(dt, use_ampm=True),
                                        'recurrence': desc,
                                        'name': alarm[2]})
        else:
            dt = self.get_alarm_local(alarm)
            dt_string = nice_date_time(dt, now=now_local(), use_ampm=True)
            if alarm[2]:
                return self.translate('alarm.named',
                        data={'datetime': dt_string,
                              'name': alarm[2]})
            else:
                return dt_string
        
    @intent_handler(IntentBuilder("").require("Query").optionally("Next").
                    require("Alarm").optionally("Recurring"))
    def handle_status(self, message):
        
        utt = message.data.get("utterance")
        
        status, alarms = self._get_alarm_matches(utt, 
                                                 alarm=self.settings["alarm"], 
                                                 max_results=3,
                                                 dialog='ask.which.alarm',
                                                 is_response=False)
        total = None
        if not alarms:
            self.speak_dialog("alarms.list.empty")
            return
        else:
            total = len(alarms)

        desc = []
        for alarm in alarms:
            desc.append(self._describe(alarm))
        
        items_string = ''
        if desc:    
            items_string = join_list(desc, self.translate('and'))

        if status == 'No Match Found':
            self.dialog('alarm.not.found')
        elif status == 'User Cancelled':
            return
        elif status == 'Next':
            reltime = nice_relative_time(self.get_alarm_local(alarms[0]))

            self.speak_dialog("next.alarm",
                              data={"when": self._describe(alarms[0]),
                                    "duration": reltime})
        else:
            if total == 1:
                reltime = nice_relative_time(self.get_alarm_local(alarms[0]))
                self.speak_dialog("alarms.list.single",
                                  data={'item': desc[0],
                                        'duration': reltime})
            else:
                self.speak_dialog("alarms.list.multi",
                                data={'count': total,
                                      'items': items_string})
    
    def _get_alarm_matches(self, utt, alarm=None, max_results=1,
                           dialog='ask.which.alarm', is_response=False):
        """ 
            Get list of timers that match based on a user utterance
            Args:
                utt (str): string spoken by the user
                timers (list): list of alarm to match against
                max_results (int): max number of results desired
                dialog (str): name of dialog file used for disambiguation
                is_response (bool): is this being called by get_response
            Returns:
                (str): ["All", "Matched", "No Match Found", or "User Cancelled"]
                (list): list of matched alarm
        """
        alarms = alarm or self.settings['alarm']
        all_words = self.translate_list('all')
        next_words = self.translate_list('next')
        status = ["All", "Matched", "No Match Found", "User Cancelled", "Next"]
        
        # No alarms
        if alarms is None or len(alarms) == 0:
            self.log.error("Cannot get match. No active timers.")
            return (status[2], None)
        
        # Extract Alarm Time
        when = extract_datetime(utt)
        utt_no_datetime = None
        if not when == None:
            utt_no_datetime = when[1]
            when = when[0]
            
        # Will return dt of unmatched string
        today = extract_datetime("today")
        today = today[0]
        
        # Check the time if it's midnight. This is to check if the user
        # said a recurring alarm with only the Day or if the user did 
        # specify to set an alarm on midnight. If it's confirmed that 
        # it's for a day only, then get another response from the user 
        # to clarify what time on that day the recurring alarm is.
        is_midnight = self._check_if_utt_has_midnight(utt,
                                                      when,
                                                      self.threshold)
        
        if when == today and not is_midnight:
            when = None    
    
        time_matches = None
        time_alarm = None
        if when:
            time_alarm = to_utc(when).timestamp()
            time_matches = [a for a in alarms if abs(a[0] - time_alarm) <= 60]
        
        # Extract Recurrence        
        recur = None
        recurrence_matches = None
        for word in self.recurrence_dict:
            is_match = self._fuzzy_match(word, utt.lower(), self.threshold)
            if is_match:
                recur = self._create_day_set(utt)
                alarm_recur = self._create_recurring_alarm(when, recur)
                recurrence_matches = [a for a in alarms if a[1] == alarm_recur[1]]
                break
        
        utt = utt_no_datetime or utt
        
        # Extract Ordinal/Cardinal Numbers
        number = extract_number(utt, ordinals=True)
        if number and number > 0:
            number = int(number)
        else:
            number = None
            
        # Extract Name
        name_matches = [a for a in alarms if a[2] and \
                        self._fuzzy_match(a[2], utt, self.threshold)]
        
        # Match Everything
        alarm_to_match = None
        if when:                
            if recur:
                alarm_to_match = alarm_recur
                
            else:
                alarm_to_match = [time_alarm, ""]
        
        # Find the Intersection of the Alarms list and all the matched alarms
        orig_count = len(alarms)
        if when and time_matches:
            alarms = [a for a in alarms if a in time_matches]
        if recur and recurrence_matches:
            alarms = [a for a in alarms if a in recurrence_matches]
        if name_matches:
            alarms = [a for a in alarms if a in name_matches]
            
        # Utterance refers to all alarms
        if utt and any(self._fuzzy_match(i, utt, 1) for i in all_words):
            return (status[0], alarms)
        # Utterance refers to the next alarm to go off
        elif utt and any(self._fuzzy_match(i, utt, 1) for i in next_words):
            return (status[4], [alarms[0]])
        
        # Given something to match but no match found
        if (number and number > len(alarm)) or \
           (recur and not recurrence_matches) or \
           (when and not time_matches):
            return (status[2], None)
        # If number of alarms filtered were the same, assume user asked for
        # All alarms    
        if len(alarms) == orig_count and max_results > 1 and \
            not number and not when and not recur:
            return (status[0], alarms)
        # Return immediately if there is ordinal
        if number and number <= len(alarms):
            return (status[1], [alarms[number - 1]])
        # Return immediately if within maximum results
        elif alarms and len(alarms) <= max_results:
            return (status[1], alarms)
        # Ask for reply from user and iterate the function
        elif alarms and len(alarms) > max_results:
            desc = []
            for alarm in alarms:
                desc.append(self._describe(alarm))            
                
            items_string = ''
            if desc:    
                items_string = join_list(desc, self.translate('and'))
                
            reply = self.get_response(dialog, data = {
                'number': len(alarms),
                'list': items_string,
            }, num_retries = 1)
            if reply:
                return self._get_alarm_matches(reply,
                                               alarm=alarms,
                                               max_results=max_results,
                                               dialog=dialog,
                                               is_response=True)
            else:
                return (status[3], None)
        
        # No matches found
        return (status[2], None)
            
    def _fuzzy_match(self, word, phrase, threshold):
        """ 
            Search a phrase to another phrase using fuzzy_match. Matches on a
            per word basis, and will not match if word is a subword.
            Args:
                word (str): string to be searched on a phrase
                phrase (str): string to be matched against the word
                threshold (int): minimum fuzzy matching score to be considered a
                    match
            Returns:
                (boolean): True if word is found in phrase. False if not.
        """
        matched = False
        score = 0
        phrase_split = phrase.split(' ')
        word_split_len = len(word.split(' '))
        
        for i in range(len(phrase_split) - word_split_len, -1, -1):
            phrase_comp = ' '.join(phrase_split[i:i + word_split_len])
            score_curr = fuzzy_match(phrase_comp, word.lower())
            
            if score_curr > score and score_curr >= threshold:
                score = score_curr
                matched = True
                
        return matched

    @intent_handler(IntentBuilder("").require("Delete").require("Alarm"))
    def handle_delete(self, message):
        total = len(self.settings["alarm"])
        if not total:
            self.speak_dialog("alarms.list.empty")
            return

        utt = message.data.get("utterance") or ""
        
        status, alarms = self._get_alarm_matches(utt, 
                                                 alarm=self.settings["alarm"], 
                                                 max_results=1,
                                                 dialog='ask.which.alarm.delete',
                                                 is_response=False)
        
        if alarms:
            total = len(alarms)
        else:
            total = None

        if total == 1:
            desc = self._describe(alarms[0])
            recurring = ".recurring" if alarms[0][1] else ""
            if self.ask_yesno('ask.cancel.desc.alarm' + recurring,
                              data={'desc': desc}) == 'yes':
                del self.settings["alarm"]\
                    [self.settings["alarm"].index(alarms[0])]
                self._schedule()
                self.speak_dialog("alarm.cancelled.desc" + recurring,
                                  data={'desc': desc})
                return
            else:
                self.speak_dialog("alarm.delete.cancelled")
                # As the user did not confirm to delete
                # return True to skip all the remaining conditions
                return
        elif status in ['Next', 'All', 'Matched']:
            if self.ask_yesno('ask.cancel.alarm.plural',
                              data={"count": total}) == 'yes':
                for a in alarms:
                    del self.settings["alarm"]\
                        [self.settings["alarm"].index(a)]
                    self._schedule()
                self.speak_dialog('alarm.cancelled.multi',
                                data = {"count": total})
            return
        elif not total:
            # Failed to delete
            self.speak_dialog("alarm.not.found")
        
        return

    def _alarm_expired(self):
        self.sound_name = self.settings["sound"]  # user-selected alarm sound
        if not self.sound_name or self.sound_name not in self.sounds:
            # invalid sound name, use the default
            self.sound_name = AlarmSkill.default_sound

        if self.settings['start_quiet'] and self.mixer:
            if not self.saved_volume:  # don't overwrite if already saved!
                self.saved_volume = self.mixer.getvolume()
                self.volume = 0    # increase by 10% each pass
        else:
            self.saved_volume = None
        
        self._disable_listen_beep()
        
        self._play_beep()
        
        # Once a second Flash the alarm and auto-listen
        self.flash_state = 0
        self.enclosure.deactivate_mouth_events()
        alarm = self.settings["alarm"][0]
        self.schedule_repeating_event(self._while_beeping, 0, 1,
                                    name='Flash',
                                    data={"alarm_time": alarm[0]})

    def __end_beep(self):
        self.cancel_scheduled_event('Beep')
        self.beep_start_time = None
        if self.beep_process:
            try:
                if self.beep_process.poll() == None:    # still running
                    self.beep_process.kill()
            except:
                pass
            self.beep_process = None
        self._restore_volume()
        self._restore_listen_beep()

    def __end_flash(self):
        self.cancel_scheduled_event('Flash')
        self.enclosure.mouth_reset()
        self.enclosure.activate_mouth_events()

    def _stop_expired_alarm(self):
        if self.has_expired_alarm():
            self.__end_beep()
            self.__end_flash()
            self.cancel_scheduled_event('NextAlarm')

            self._curate_alarms(0)  # end any expired alarm
            self._schedule()
            return True
        else:
            return False

    def _restore_volume(self):
        # Return global volume to the appropriate level if we've messed with it
        if self.saved_volume:
            self.mixer.setvolume(self.saved_volume[0])
            self.saved_volume = None

    def _disable_listen_beep(self):
        user_config = LocalConf(USER_CONFIG)

        if 'user_beep_setting' not in self.settings:
            # Save any current local config setting
            self.settings['user_beep_setting'] = user_config.get("confirm_listening", None)

            # Disable in local config
            user_config.merge({"confirm_listening": False})
            user_config.store()

            # Notify all processes to update their loaded configs
            self.bus.emit(Message('configuration.updated'))

    def _restore_listen_beep(self):
        if 'user_beep_setting' in self.settings:
            # Wipe from local config
            new_conf_values = {"confirm_listening": False}
            user_config = LocalConf(USER_CONFIG)

            if self.settings["user_beep_setting"] is None and \
                            "confirm_listening" in user_config:
                del user_config["confirm_listening"]
            else:
                user_config.merge({"confirm_listening":
                                   self.settings["user_beep_setting"]})
            user_config.store()

            # Notify all processes to update their loaded configs
            self.bus.emit(Message('configuration.updated'))
            del self.settings["user_beep_setting"]

    def converse(self, utterances, lang="en-us"):
        if self.has_expired_alarm():
            # An alarm is going off
            if utterances and self.voc_match(utterances[0], "StopBeeping"):
                # Stop the alarm
                self._stop_expired_alarm()
                return True  # and consume this phrase

    @intent_file_handler('snooze.intent')
    def snooze_alarm(self, message):
        if not self.has_expired_alarm():
            return

        self.__end_beep()
        self.__end_flash()

        utt = message.data.get('utterance') or ""
        snooze_for = extract_number(utt)
        if not snooze_for or snooze_for < 1:
            snooze_for = 9  # default to 9 minutes

        # Snooze always applies the the first alarm in the sorted array
        alarm = self.settings["alarm"][0]
        dt = self.get_alarm_local(alarm)
        snooze = to_utc(dt) + timedelta(minutes=snooze_for)

        if len(alarm) < 3:
            original_time = alarm[0]
        else:
            original_time = alarm[2]  # already snoozed

        # Fill schedule with a snoozed entry -- 3 items:
        #    snooze_expire_timestamp, repeat_rule, original_timestamp
        self.settings["alarm"][0] = [snooze.timestamp(),
                                     alarm[1],
                                     original_time]
        self._schedule()

    def _play_beep(self, message=None):
        """ Play alarm sound file """
        now = now_local()

        if not self.beep_start_time:
            self.beep_start_time = now
        elif (now - self.beep_start_time).total_seconds() > self.settings["max_alarm_secs"]:
            # alarm has been running long enough, auto-quiet it
            self.log.info("Automatically quieted alarm after 10 minutes")
            self._stop_expired_alarm()
            return

        # Validate user-selected alarm sound file
        alarm_file = join(abspath(dirname(__file__)),
                          'sounds', self.sound_name + ".mp3")
        if not os.path.isfile(alarm_file):
            # Couldn't find the required sound file
            self.sound_name = AlarmSkill.default_sound
            alarm_file = join(abspath(dirname(__file__)),
                            'sounds', self.sound_name + ".mp3")

        beep_duration = self.sounds[self.sound_name]
        repeat_interval = beep_duration + AlarmSkill.beep_gap

        next_beep = now + timedelta(seconds=repeat_interval)
        end_of_beep = now + timedelta(seconds=(beep_duration+1))

        self.cancel_scheduled_event('Beep')
        self.schedule_event(self._play_beep, to_system(next_beep), name='Beep')
        try:
            if self.beep_process and self.beep_process.poll() == None:
                self.beep_process.kill()
        except:
            self.beep_process = None

        # Increase volume each pass until fully on
        if self.saved_volume:
            if self.volume < 90:
                self.volume += 10
            self.mixer.setvolume(self.volume)

        try:
            self.beep_process = play_mp3(alarm_file)
        except:
            self.beep_process = None

    def stop(self):
        return self._stop_expired_alarm()
    
    @intent_file_handler('change.alarm.sound.intent')
    def handle_change_alarm(self, message):
        self.speak_dialog("alarm.change.sound")
        

def create_skill():
    return AlarmSkill()


##########################################################################
# TODO: Move to mycroft.util.format and support translation

def nice_relative_time(when, relative_to=None, lang=None):
    """ Create a relative phrase to roughly describe a datetime

    Examples are "25 seconds", "tomorrow", "7 days".

    Args:
        when (datetime): Local timezone
        relative_to (datetime): Baseline for relative time, default is now()
        lang (str, optional): Defaults to "en-us".
    Returns:
        str: Relative description of the given time
    """
    if relative_to:
        now = relative_to
    else:
        now = now_local()
    delta = (to_local(when) - now)

    if delta.total_seconds() < 1:
        return "now"

    if delta.total_seconds() < 90:
        if delta.total_seconds() == 1:
            return "one second"
        else:
            return "{} seconds".format(int(delta.total_seconds()))

    minutes = int((delta.total_seconds()+30) // 60)  # +30 to round minutes
    if minutes < 90:
        if minutes == 1:
            return "one minute"
        else:
            return "{} minutes".format(minutes)

    hours = int((minutes+30) // 60)  # +30 to round hours
    if hours < 36:
        if hours == 1:
            return "one hour"
        else:
            return "{} hours".format(hours)

    # TODO: "2 weeks", "3 months", "4 years", etc
    days = int((hours+12) // 24)  # +12 to round days
    if days == 1:
        return "1 day"
    else:
        return "{} days".format(days)
