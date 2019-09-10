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
        self.register_entity_file('and.entity')
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

    def set_alarm(self, when, repeat=None):
        if repeat:
            alarm = self._create_recurring_alarm(when, repeat)
        else:
            alarm = [to_utc(when).timestamp(), ""]

        for existing in self.settings["alarm"]:
            if alarm == existing:
                self.speak_dialog("alarm.already.exists")
                return

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
            ref = datetime.fromtimestamp(alarm[2])  # repeat from original time (it was snoozed)
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
        now = extract_datetime("dummy")  # Will return dt of unmatched string
        while not when or when[0] == now[0]:
            # No time given, ask for one
            r = self.get_response('query.for.when', num_retries=1)
            if not r:
                return
            when = extract_datetime(r)

        # Verify time
        alarm_time = when[0]
        confirmed_time = False
        while not when or when[0] == now[0]:
            if recur:
                t = nice_time(alarm_time, use_ampm=True)
                conf = self.ask_yesno('confirm.recurring.alarm',
                                      data={'time': t,
                                            'recurrence': self._recur_desc(recur)})
            else:
                t = nice_date_time(alarm_time, now=now[0], use_ampm=True)
                conf = self.ask_yesno('confirm.alarm', data={'time': t})
            if not conf:
                return
            if conf == 'yes':
                when = [alarm_time]
                confirmed_time = True
            else:
                # check if a new (corrected) time was given
                when = extract_datetime(conf)
                if not when or when[0] == now[0]:
                    # Not a confirmation and no date/time in statement, quit
                    return
                alarm_time = when[0]
                when = None  # reverify

        alarm = None
        if not recur:
            alarm_time_ts = to_utc(alarm_time).timestamp()
            now_ts = now_utc().timestamp()
            if alarm_time_ts > now_ts:
                alarm = self.set_alarm(alarm_time)
            else:
                if ('today' in utt) or ('tonight' in utt):
                    self.speak_dialog('alarm.past')
                    return
                else:
                    # Set the alarm on next weekday
                    alarm_time_ts += 7 * 86400.0
                    alarm_time = datetime.utcfromtimestamp(alarm_time_ts)
                    alarm = self.set_alarm(alarm_time)
        else:
            alarm = self.set_alarm(alarm_time, repeat=recur)

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
                desc = "repeats"

            dt = self.get_alarm_local(alarm)
            return self.translate('recurring.alarm',
                                  data={'time': nice_time(dt, use_ampm=True),
                                        'recurrence': desc})
        else:
            dt = self.get_alarm_local(alarm)
            return nice_date_time(dt, now=now_local(), use_ampm=True)

    @intent_file_handler('query.next.alarm.intent')
    def handle_query_next(self, message):
        total = len(self.settings["alarm"])
        if not total:
            self.speak_dialog("alarms.list.empty")
            return

        alarm = self.settings["alarm"][0]
        reltime = nice_relative_time(self.get_alarm_local(alarm))

        self.speak_dialog("next.alarm", data={"when": self._describe(alarm),
                                              "duration": reltime})

    @intent_file_handler('alarm.status.intent')
    def handle_status(self, message):
        total = len(self.settings["alarm"])
        if not total:
            self.speak_dialog("alarms.list.empty")
            return

        desc = []
        for alarm in self.settings["alarm"]:
            desc.append(self._describe(alarm))
            if len(desc) > 3:
                break
        
        items_string = ''
        if desc:    
            items_string = join_list(desc, self.translate('and'))

        if total == 1:
            self.speak_dialog("alarms.list.single", data={'item': desc[0]})
        else:
            self.speak_dialog("alarms.list.multi",
                              data={'count': total,
                                    'items': items_string})

    @intent_handler(IntentBuilder("").require("Delete").require("All").
                    require("Alarm"))
    def handle_delete_all(self, message):
        total = len(self.settings["alarm"])
        if not total:
            self.speak_dialog("alarms.list.empty")
            return

        # Confirm cancel alarms...
        recurring = ".recurring" if self.settings["alarm"][0][1] else ""
        prompt = ('ask.cancel.alarm' + recurring if total == 1
                  else 'ask.cancel.alarm.plural')
        if self.ask_yesno(prompt, data={"count": total}) == 'yes':
            self.settings["alarm"] = []
            self._schedule()
            self.speak_dialog('alarms.cancelled')

    def _delete_alarm_with_dt(self,when,utt):
        # This method takes the utterance and extracted date-time (if any)
        # and matches the timestamp with list of alarms. When a match is
        # found we delete that particular alarm and return. If no timestamp
        # is matched with the request, then we ask the user to specify
        # time and day. Then we check the same conditions above.
        # This also handles special cases when no time/day is specified
        # Ex : morning, weekdays, weekends etc.

        # Look for a match...
        search = when[0]
        when_utc = to_utc(search).timestamp()
        self.log.debug("when_utc obtained is : " + str(when_utc))
        alarm = None
        # From the list of alarms, find the one that has same timestamp
        # This condition gets alarm from all other cases
        if 'weekend' not in utt:
            for row in self.settings["alarm"]:
                if when_utc == row[0]:
                    alarm = row
                    break

        # Not sure if this is a faster approach
        # TODO: Make a single condition for all the cases
        elif 'weekend' in utt:
            for row in self.settings["alarm"]:
                if row[1] and 'BYDAY=SU,SA' in row[1]:
                        for day in range(7):
                            if (when_utc + (day * 86400.0)) == row[0]:
                                alarm = row
                                when_utc = when_utc + (day * 86400.0)
                                break

        if alarm:
            dt = self.get_alarm_local(alarm)
            desc = self._describe(alarm)
            delta = search - dt
            delta2 = dt - search
            recurring = ".recurring" if alarm[1] else ""
            # First check if we get the timestamp
            if when_utc == alarm[0]:
                if self.ask_yesno('ask.cancel.desc.alarm' + recurring,
                                  data={'desc': desc}) == 'yes':
                    self.settings["alarm"].remove(alarm)
                    self._schedule()
                    self.speak_dialog("alarm.cancelled" + recurring)
                    return True
                else:
                    self.speak_dialog('alarm.delete.cancelled')
                    # As the user did not confirm to delete
                    # return True to skip all the remaining conditions
                    return True

            if (abs(delta.total_seconds()) < 60 or
                    abs(delta2.total_seconds()) < 60):
                # Really close match, just delete it
                # desc = self._describe(alarm)
                self.settings["alarm"].remove(alarm)
                self._schedule()
                self.speak_dialog("alarm.cancelled.desc" + recurring,
                                  data={'desc': desc})
                return True

            if (abs(delta.total_seconds()) < 60 * 60 * 2 or
                    abs(delta2.total_seconds()) < 60 * 60 * 2):
                # Not super close, get confirmation
                if self.ask_yesno('ask.cancel.desc.alarm' + recurring,
                                  data={'desc': desc}) == 'yes':
                    self.settings["alarm"].remove(alarm)
                    self._schedule()
                    self.speak_dialog("alarm.cancelled" + recurring)
                    return True
                else:
                    self.speak_dialog('alarm.delete.cancelled')
                    # As the user did not confirm to delete
                    # return True to skip all the remaining conditions
                    return True
        else:
            # If no alarm is present check the remaining cases if any
            return False

    #@intent_file_handler('delete.intent')
    @intent_handler(IntentBuilder("").require("Delete").require("Alarm"))
    def handle_delete(self, message):
        total = len(self.settings["alarm"])
        if not total:
            self.speak_dialog("alarms.list.empty")
            return

        utt = message.data.get("utterance") or ""

        # First see if the user spoke a date/time in the delete request
        when = extract_datetime(utt)
        now = extract_datetime("now")

        if when and when[0] != now[0]:
            if self._delete_alarm_with_dt(when, utt):
                return

        if total == 1:
            alarm = self.settings["alarm"][0]
            desc = self._describe(alarm)
            recurring = ".recurring" if alarm[1] else ""
            if self.ask_yesno('ask.cancel.desc.alarm' + recurring,
                              data={'desc': desc}) == 'yes':
                self.settings["alarm"] = []
                self._schedule()
                self.speak_dialog("alarm.cancelled" + recurring)
                return
            else:
                self.speak_dialog("alarm.delete.cancelled")
                # As the user did not confirm to delete
                # return True to skip all the remaining conditions
                return
        else:
            self.handle_status(message)
            resp = self.get_response('ask.which.alarm.delete')
            if not resp:
                return
            # From the response we perform the same conditions above
            when = extract_datetime(resp)
            if when and when[0] != now[0]:
                if self._delete_alarm_with_dt(when, str(resp)):
                    return

            # Attempt to delete by spoken index
            idx = extract_number(resp, ordinals=True)
            if idx and idx > 0 and idx <= total:
                idx = int(idx)
                alarm = self.settings["alarm"][idx-1]
                desc = self._describe(alarm)
                recurring = ".recurring" if alarm[1] else ""
                del self.settings["alarm"][idx-1]
                self._schedule()
                self.speak_dialog("alarm.cancelled" + recurring, data={'desc': desc})
                return

            # Attempt to match by words, e.g. "all", "both"
            if self.voc_match(resp, 'All'):
                self.settings["alarm"] = []
                self._schedule()
                self.speak_dialog('alarms.cancelled')
                return

            # Failed to delete
            self.speak_dialog("alarm.not.found")

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

            if self.settings["user_beep_setting"] is None and\
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
            if self.voc_match(utterances[0], "StopBeeping"):
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
