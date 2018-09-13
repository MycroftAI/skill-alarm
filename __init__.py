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
import os.path
from alsaaudio import Mixer

from adapt.intent import IntentBuilder
from mycroft import MycroftSkill, intent_handler, intent_file_handler
from mycroft.audio import wait_while_speaking
from mycroft.configuration.config import LocalConf, USER_CONFIG
from mycroft.messagebus.message import Message
from mycroft.util import play_wav, play_mp3
from mycroft.util.format import nice_date_time, nice_time
from mycroft.util.log import LOG
from mycroft.util.parse import fuzzy_match, extract_datetime, extract_number
from dateutil.parser import parse
from dateutil.rrule import rrulestr
from mycroft.util.time import (
    to_utc, default_timezone, to_local, now_local, now_utc)

# WORKING:
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
# #
# TODO:
# Set a recurring alarm for mondays and wednesdays at 7
# Set an alarm for 10 am every weekday  - Adapt is missing "every"

class AlarmSkill(MycroftSkill):

    def __init__(self):
        super(AlarmSkill, self).__init__()
        self.beep_process = None
        self._should_play_beep = True
        self.settings['alarms'] = []    # OLD, [(str(datetime),name), ...]
        self.settings['repeat_alarms'] = []

        self.settings['max_alarm_secs'] = 10*60  # max time to beep: 10 min
        self.beep_start_time = None

        # Seconds of gap between sound repeats.
        # The value name must match an option from the 'sound' value of the
        # settingmeta.json, which also corresponds to the name of an mp3
        # file in the skill's sounds/ folder.  E.g. <skill>/sounds/bell.mp3
        #
        self.sound_interval = {
            "bell": 9.07,
            "escalate": 40.0,
            "constant_beep": 10.0,
            "beep4": 7.0
        }
        # default sound is 'constant_beep'
        self.settings['sound'] = 'constant_beep'
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
        #       snoozed alarm
        # NOTE: Using list instead of tuple because of serialization
        self.settings["alarm"] = []

    def dump_alarms(self, tag=""):
        # Useful when debugging
        self.log.info("********** ALARMS "+tag+"*************")
        self.log.info(self.settings["alarm"])
        idx = 1
        for alarm in self.settings["alarm"]:
            timestamp_time = alarm[0]
            dt = datetime.fromtimestamp(timestamp_time)
            self.log.info(str(idx) + " - " + str(alarm) +
                          "  U" + str(dt) + " L" + str(to_local(dt)))
            idx += 1

        now_ts = now_utc().timestamp()
        dt = datetime.fromtimestamp(now_ts)
        self.log.info("-"*40)
        self.log.info("NOW: " + str(now_ts) +
                      "  U" + str(to_utc(dt)) + " L" + str(to_local(dt)))

        self.log.info("*"*60)

    def initialize(self):
        self.register_entity_file('daytype.entity')  # TODO: Keep?
        self.recurrence_dict = self.translate_namedvalues('recurring')

        # Time is the first value, so this will sort alarms by time
        self.settings["alarm"].sort()

        # This will reschedule alarms which have expired within the last
        # 5 minutes, and cull anything older.
        self._curate_alarms(5*60)

        self._schedule()

    def set_alarm(self, when, repeat=None):
        if repeat:
            alarm = self._create_recurring_alarm(when, repeat)
        else:
            alarm = [to_utc(when).timestamp(), ""]

        self.settings["alarm"].append(alarm)
        self._schedule()
        return alarm

    def _schedule(self):
        # cancel any existing timed event
        self.cancel_scheduled_event('NextAlarm')
        self._curate_alarms()

        # set timed event for next alarm (if it exists)
        if self.settings["alarm"]:
            timestamp_time = self.settings["alarm"][0][0]
            dt = datetime.fromtimestamp(timestamp_time)
            self.schedule_event(self._alarm_expired,
                                to_utc(dt),
                                name='NextAlarm')

    def _curate_alarms(self, curation_limit=1):
        """[summary]
            curation_limit (int, optional): Seconds past expired at which to
                                            remove the alarm
        """
        alarms = []
        now_ts = now_utc().timestamp()
        for alarm in self.settings["alarm"]:
            if alarm[0] < now_ts:
                if alarm[0] < (now_ts - curation_limit):
                    # skip playing an old alarm (but resched if needed)
                    if alarm[1]:
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
        r = rrulestr("RRULE:" + alarm[1])
        if len(alarm) == 3:
            ref = datetime.fromtimestamp(alarm[2])
        else:
            ref = datetime.fromtimestamp(alarm[0])

        local_ref_notz = to_local(ref).replace(tzinfo=None)
        dt_next_local = r.after(local_ref_notz)

        return [to_utc(dt_next_local).timestamp(), alarm[1]]

    def _create_recurring_alarm(self, when, repeat):
        # 'repeat' is one of the values in the self.recurrence_dict
        # convert rule into an iCal rrule
        # TODO: Support more complex alarms, e.g. first monday, monthly, etc
        reps = self.recurrence_dict[repeat].split()
        rule = ""
        abbr = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]
        days = []
        for day in reps:
            days.append(abbr[int(day)])
        if days:
            rule = "FREQ=WEEKLY;INTERVAL=1;BYDAY=" + ",".join(days)

        return [to_utc(when).timestamp(), rule]

    def has_expired_alarm(self):
        # True is an alarm should be 'going off' now.  Snoozed alarms don't
        # count until the are triggered again.
        if not self.settings["alarm"]:
            return False

        now_ts = now_utc().timestamp()
        for alarm in self.settings["alarm"]:
            if alarm[0] <= now_ts:
                return True

        return False

    # Wake me on ... (hard to match with Adapt entities)
    @intent_handler(IntentBuilder("").require("WakeMe").
                    optionally("Recurring").optionally("Recurrence"))
    def handle_wake_me(self, message):
        self.handle_set_alarm(message)

    # Set an alarm for ...
    @intent_handler(IntentBuilder("").require("Set").require("Alarm").
                    optionally("Recurring").optionally("Recurrence"))
    def handle_set_alarm(self, message):
        utt = message.data.get('utterance').lower()
        recurrence = None

        if message.data.get('Recurring'):
            recurrence = message.data.get('Recurrence')
            if not recurrence:
                # a bug in Adapt is missing the recurrence.voc.  Look ourselves
                for r in self.recurrence_dict:
                    if r in utt:
                        recurrence = r

            while recurrence not in self.recurrence_dict:
                r = self.get_response('query.recurrence', num_retries=1)
                if not r:
                    return
                recurrence = r

        # Get the time
        when = extract_datetime(utt)
        now = extract_datetime("now")
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
            if recurrence:
                t = nice_time(alarm_time, use_ampm=True)
                conf = self.ask_yesno('confirm.recurring.alarm',
                                      data={'time': t,
                                            'recurrence': recurrence})
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

        if not recurrence:
            alarm = self.set_alarm(alarm_time)
        else:
            alarm = self.set_alarm(alarm_time, repeat=recurrence)

        # Don't want to hide the animation
        self.enclosure.deactivate_mouth_events()
        if confirmed_time:
            self.speak_dialog("alarm.scheduled")
        else:
            t = self._describe(alarm)
            reltime = nice_relative_time(datetime.fromtimestamp(alarm[0]))
            self.speak_dialog("alarm.scheduled.for.time",
                              data={"time": t, "rel": reltime})
        self._show_alarm_anim(alarm_time)
        self.enclosure.activate_mouth_events()

    @property
    def use_24hour(self):
        return self.config_core.get('time_format') == 'full'

    def _show_alarm_anim(self, dt):
        # Animated confirmation of the alarm
        self.enclosure.mouth_reset()

        # Show the time in numbers "8:00 AM"
        timestr = nice_time(dt, speech=False, use_ampm=True,
                            use_24hour=self.use_24hour)
        x = 16 - ((len(timestr)*4) // 2)  # centers on display
        if not self.use_24hour:
            x += 1  # account for wider letters P and M, offset by the colon

        # draw on the display
        for ch in timestr:
            # deal with some odd characters that can break filesystems
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

    def _describe(self, alarm):
        if alarm[1]:
            # Describe repeating alarms
            if alarm[1].startswith("FREQ=WEEKLY;INTERVAL=1;BYDAY="):
                days = alarm[1][29:]  # e.g. "SU,WE"
                days = (days.replace("SU", "0").replace("MO", "1").
                        replace("TU", "2").replace("WE", "3").
                        replace("TH", "4").replace("FR", "5").
                        replace("SA", "6").replace(",", " "))  # now "0 3"

                desc = None
                for r in self.recurrence_dict:
                    if self.recurrence_dict[r] == days:
                        desc = r
                        break    # accept the first match

                # Assemble a long desc, e.g. "Monday and wednesday"
                if not desc:
                    day_names = []
                    for day in days.split(" "):
                        for r in self.recurrence_dict:
                            if self.recurrence_dict[r] is day:
                                day_names.append(r)
                                break

                    # TODO: Make translatable. mycroft.util.format.join("and")?
                    desc = ", ".join(day_names[:-1]) + " and " + day_names[-1]
            else:
                desc = "repeats"

            dt = datetime.fromtimestamp(alarm[0], default_timezone())
            return self.translate('recurring.alarm',
                                  data={'time': nice_time(dt, use_ampm=True),
                                        'recurrence': desc})
        else:
            dt = datetime.fromtimestamp(alarm[0], default_timezone())
            return nice_date_time(dt, now=now_local(), use_ampm=True)

    @intent_file_handler('query.next.alarm.intent')
    def handle_query_next(self, message):
        total = len(self.settings["alarm"])
        if not total:
            self.speak_dialog("alarms.list.empty")
            return

        alarm = self.settings["alarm"][0]

        timestamp_time = alarm[0]
        alarm_local = datetime.fromtimestamp(timestamp_time)
        reltime = nice_relative_time(alarm_local)

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

        if total == 1:
            self.speak_dialog("alarms.list.single", data={'item': desc[0]})
        else:
            self.speak_dialog("alarms.list.multi",
                              data={'count': total,
                                    'item': ", ".join(desc[:-1]),
                                    'itemAnd': desc[-1]})

    @intent_file_handler('delete.all.intent')
    def handle_delete_all(self, message):
        total = len(self.settings["alarm"])
        if not total:
            self.speak_dialog("alarms.list.empty")
            return

        # Confirm cancel alarms...
        prompt = ('ask.cancel.alarm' if total == 1
                  else 'ask.cancel.alarm.plural')
        if self.ask_yesno(prompt, data={"count": total}) == 'yes':
            self.settings["alarm"] = []
            self._schedule()
            self.speak_dialog('alarms.cancelled')

    @intent_file_handler('delete.intent')
    def handle_delete(self, message):
        total = len(self.settings["alarm"])
        if not total:
            self.speak_dialog("alarms.list.empty")
            return

        utt = message.data.get('utterance') or ""
        time = message.data.get('time') or ""

        # First see if the user spoke a date/time in the delete request
        when = extract_datetime(utt)
        now = extract_datetime("now")
        if when and when[0] != now[0]:
            # Look for a match...
            search = when[0]
            for alarm in self.settings["alarm"]:
                # TODO: Handle repeating desc
                dt = datetime.fromtimestamp(alarm[0], default_timezone())
                delta = search - dt
                delta2 = dt - search
                if (abs(delta.total_seconds()) < 60 or
                        abs(delta2.total_seconds()) < 60):
                    # Really close match, just delete it
                    desc = self._describe(alarm)
                    self.settings["alarm"].remove(alarm)
                    self._schedule()
                    self.speak_dialog("alarm.cancelled.desc",
                                      data={'desc': desc})
                    return

                if (abs(delta.total_seconds()) < 60*60*2 or
                        abs(delta2.total_seconds()) < 60*60*2):
                    # Not super close, get confirmation
                    desc = self._describe(alarm)
                    if self.ask_yesno('ask.cancel.desc.alarm',
                                      data={'desc': desc}) == 'yes':
                        self.settings["alarm"].remove(alarm)
                        self._schedule()
                        self.speak_dialog("alarm.cancelled")
                        return

        if total == 1:
            desc = self._describe(self.settings["alarm"][0])
            if self.ask_yesno('ask.cancel.desc.alarm',
                              data={'desc': desc}) == 'yes':
                self.settings["alarm"] = []
                self._schedule()
                self.speak_dialog("alarm.cancelled")
                return
        else:
            # list the alarms
            self.handle_status(message)
            resp = self.get_response('ask.which.alarm.delete')
            if not resp:
                return

            when = extract_datetime(resp)
            if when and when[0] != now[0]:
                # Attempting to delete by spoken data
                search = when[0]
                for alarm in self.settings["alarm"]:
                    # TODO: Handle repeating desc
                    dt = datetime.fromtimestamp(alarm[0], default_timezone())
                    delta = search - dt
                    delta2 = dt - search
                    if (abs(delta.total_seconds()) < 60 or
                            abs(delta2.total_seconds()) < 60):
                        # Really close match, just delete it
                        desc = self._describe(alarm)
                        self.settings["alarm"].remove(alarm)
                        self._schedule()
                        self.speak_dialog("alarm.cancelled.desc",
                                          data={'desc': desc})
                        return

                    if (abs(delta.total_seconds()) < 60*60*2 or
                            abs(delta2.total_seconds()) < 60*60*2):
                        # Not super close, get confirmation
                        desc = self._describe(alarm)
                        if self.ask_yesno('ask.cancel.desc.alarm',
                                          data={'desc': desc}) == 'yes':
                            self.settings["alarm"].remove(alarm)
                            self._schedule()
                            self.speak_dialog("alarm.cancelled")
                            return

            # Attempt to delete by spoken index
            idx = extract_number(resp, ordinals=True)
            if idx and idx > 0 and idx <= total:
                idx = int(idx)
                desc = self._describe(self.settings["alarm"][idx-1])
                del self.settings["alarm"][idx-1]
                self._schedule()
                self.speak_dialog("alarm.cancelled", data={'desc': desc})
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
        # Find user-selected alarm sound
        alarm_file = join(abspath(dirname(__file__)),
                          'sounds', self.settings["sound"] + ".mp3")
        if os.path.isfile(alarm_file):
            self.sound_file = alarm_file
            self.sound_repeat = self.sound_interval[self.settings["sound"]]
        else:
            self.sound_file = join(abspath(dirname(__file__)),
                                   'sounds', "constant_beep.mp3")
            self.sound_repeat = self.sound_interval["constant_beep"]

        if self.settings['start_quiet'] and self.mixer:
            if not self.saved_volume:  # don't overwrite if already saved!
                self.saved_volume = self.mixer.getvolume()
                self.volume = 0    # increase by 10% each pass
        else:
            self.saved_volume = None

        self._disable_listen_beep()
        self._play_beep()

    def _stop_expired_alarm(self):
        if self.has_expired_alarm():
            self.cancel_scheduled_event('Beep')
            self.beep_start_time = None
            if self.beep_process:
                self.beep_process.kill()
                self.beep_process = None
            self._restore_volume()
            self._restore_listen_beep()

            self.cancel_scheduled_event('NextAlarm')
            self._curate_alarms(0)
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

        if not 'user_beep_setting' in self.settings:
            self.log.info("Saving beep settings.....")
            # Save any current local config setting
            self.settings['user_beep_setting'] = user_config.get("confirm_listening", None)

            # Disable in local config
            user_config.merge({"confirm_listening": False})
            user_config.store()

            # Notify all processes to update their loaded configs
            self.emitter.emit(Message('configuration.updated'))
            self.log.info("Done")

    def _restore_listen_beep(self):
        if 'user_beep_setting' in self.settings:
            self.log.info("Restoring beep settings.....")
            # Wipe from local config
            new_conf_values = {"confirm_listening": False}
            user_config = LocalConf(USER_CONFIG)

            if self.settings["user_beep_setting"] is None:
                del user_config["confirm_listening"]
            else:
                user_config.merge({"confirm_listening":
                                   self.settings["user_beep_setting"]})
            user_config.store()

            # Notify all processes to update their loaded configs
            self.emitter.emit(Message('configuration.updated'))
            del self.settings["user_beep_setting"]
            self.log.info("Done")

    @intent_file_handler('snooze.intent')
    def snooze_alarm(self, message):
        if not self.has_expired_alarm():
            return

        self.cancel_scheduled_event('Beep')
        if self.beep_process:
            self.beep_process.kill()
            self.beep_process = None
        self._restore_volume()
        self._restore_listen_beep()

        utt = message.data.get('utterance') or ""
        snooze_for = extract_number(utt)
        if not snooze_for or snooze_for < 1:
            snooze_for = 9  # default to 9 minutes

        # Snooze always applies the the first alarm in the sorted array
        alarm = self.settings["alarm"][0]
        dt = datetime.fromtimestamp(alarm[0])
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

    def _play_beep(self):
        """ Play alarm sound file """
        now = now_utc()

        if not self.beep_start_time:
            self.beep_start_time = now
        elif (now - self.beep_start_time).total_seconds() > self.settings["max_alarm_secs"]:
            # alarm has been running long enough, auto-quiet it
            self.log.info("Automatically quieted alarm after 10 minutes")
            self._stop_expired_alarm()
            return

        next_beep = now + timedelta(seconds=(self.sound_repeat))
        self.schedule_event(self._play_beep, next_beep, name='Beep')
        if self.beep_process:
            self.beep_process.kill()

        # Increase volume each pass until fully on
        if self.saved_volume:
            if self.volume < 90:
                self.volume += 10
            self.mixer.setvolume(self.volume)

        self.beep_process = play_mp3(self.sound_file)

        # Listen for cries of "Stop!!!"
        #if not self.is_listening:
        self.bus.emit(Message('mycroft.mic.listen'))

    @intent_file_handler('stop.intent')
    def handle_alternative_stop(self, message):
        self.stop()

    def stop(self):
        return self._stop_expired_alarm()


def create_skill():
    return AlarmSkill()


##########################################################################
# TODO: Move to mycroft.util.format and support translation

def nice_relative_time(when, lang="en-us"):
    """ Create a relative phrase to roughly describe a datetime

    Examples are "25 seconds", "tomorrow", "7 days".

    Args:
        when (datetime): Local timezone
        lang (str, optional): Defaults to "en-us".
        speech (bool, optional): Defaults to True.
    Returns:
        str: description of the given time
    """
    now = now_local()
    delta = (to_local(when) - now)

    if delta.total_seconds() < 1:
        return "now"

    if delta.total_seconds() < 90:
        return "{} seconds".format(int(delta.total_seconds()))

    minutes = int(delta.total_seconds() // 60)
    if minutes < 90:
        return "{} minutes".format(minutes)

    hours = int(minutes // 60)
    if hours < 36:
        return "{} hours".format(hours)

    # TODO: "2 weeks", "3 months", "4 years", etc
    return "{} days".format(int(hours // 24))







