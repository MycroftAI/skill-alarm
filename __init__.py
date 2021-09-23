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

import pytz
from datetime import datetime, timedelta
from os.path import join, abspath, dirname, isfile
import re
import time
from alsaaudio import Mixer
from adapt.intent import IntentBuilder
from mycroft import MycroftSkill, intent_handler
from mycroft.messagebus.message import Message
from mycroft.skills import skill_api_method
from mycroft.util import play_mp3
from mycroft.util.format import nice_date_time, nice_time, nice_date, join_list, date_time_format
from mycroft.util.parse import extract_datetime, extract_number
from mycroft.util.time import to_utc, now_local, now_utc

from mycroft.util.time import to_system

from .lib.alarm import (
    alarm_log_dump,
    curate_alarms,
    get_alarm_local,
    get_next_repeat,
    has_expired_alarm,
)
from .lib.format import nice_relative_time
from .lib.parse import fuzzy_match, utterance_has_midnight
from .lib.recur import (
    create_day_set,
    create_recurring_rule,
    describe_recurrence,
    describe_repeat_rule,
)

# WORKING PHRASES/SEQUENCES:
# See VK Tests for requirements/usage.
# TODO: Context - save the alarm found in queries as context
#   When is the next alarm
#   >  7pm tomorrow
#   Cancel it

class AlarmSkill(MycroftSkill):
    """The official Alarm Skill for Mycroft AI."""

    # seconds between end of a beep and the start of next
    # must be bigger than the max listening time (10 sec)
    BEEP_GAP = 15
    DEFAULT_SOUND = "constant_beep"
    THRESHOLD = 0.7  # Threshold for word fuzzy matching

    def __init__(self):
        super(AlarmSkill, self).__init__()
        self.beep_process = None
        self.beep_start_time = None
        self.flash_state = 0
        self.recurrence_dict = None
        self.sound_name = None
        self.skill_control.category = 'system'
        self.weekdays = None
        self.months = None

        # Seconds of gap between sound repeats.
        # The value name must match an option from the 'sound' value of the
        # settingmeta.json, which also corresponds to the name of an mp3
        # file in the skill's sounds/ folder.  E.g. <skill>/sounds/bell.mp3
        #
        self.sounds = {
            "bell": 5.0,
            "escalate": 32.0,
            "constant_beep": 5.0,
            "beep4": 4.0,
            "chimes": 22.0,
        }

        # initialize alarm settings
        self.init_settings()
        try:
            self.mixer = Mixer()
        except Exception:
            # Retry instanciating the mixer
            try:
                self.mixer = Mixer()
            except Exception as err:
                self.log.warning("Couldn't allocate mixer, {}".format(repr(err)))
                self.mixer = None
        self.saved_volume = None

        # Alarm list format [{
        #                      "timestamp": float,
        #                      "repeat_rule": str,
        #                      "name": str,
        #                      "snooze": float
        #                    }, ...]
        # where:
        #  timestamp is a POSIX timestamp float assumed to
        #       be in the utc timezone.
        #
        #  repeat_rule is for generating the next in a series.  Valid
        #       repeat_rules include None for a one-shot alarm or any other
        #       iCalendar rule from RFC <https://tools.ietf.org/html/rfc5545>.
        #
        #  name is the name of the alarm. There can be multiple alarms of the
        #       same name.
        #
        #  snooze is the POSIX timestamp float of the Snooze assumed to
        #       be in the utc timezone.
        #
        # NOTE: Using list instead of tuple because of serialization

    def init_settings(self):
        """Add any missing default settings."""
        # default sound is 'constant_beep'
        self.settings.setdefault("max_alarm_secs", 10 * 60)  # Beep for 10 min.
        self.settings.setdefault("sound", self.DEFAULT_SOUND)
        self.settings.setdefault("start_quiet", True)
        self.settings.setdefault("alarm", [])

    def initialize(self):
        """Executed immediately after Skill has been initialized."""
        self.ver = "1.0-k"
        self.skill_control.category = 'system'
        self.register_entity_file("daytype.entity")  # TODO: Keep?
        self.recurrence_dict = self.translate_namedvalues("recurring")

        # Time is the first value, so this will sort alarms by time
        self.settings["alarm"] = sorted(
            self.settings["alarm"], key=lambda a: a["timestamp"]
        )

        # This will reschedule alarms which have expired within the last
        # 5 minutes, and cull anything older.
        self.settings["alarm"] = curate_alarms(self.settings["alarm"], 5 * 60)

        self._schedule()

        # TODO: remove the "private.mycroftai.has_alarm" event in favor of the
        #   "skill.alarm.query-active" event.
        self.add_event("private.mycroftai.has_alarm", self.on_has_alarm)
        self.add_event("skill.alarm.query-active", self.handle_active_alarm_query)

        # establish local timezone from config
        self.local_tz = self.location_timezone
        self.log.info("Local timezone configured for %s" % (self.local_tz,))

        date_time_format.cache(self.lang)
        if self.lang in date_time_format.lang_config.keys():
            self.weekdays = list(date_time_format.lang_config[self.lang]['weekday'].values())
            self.months = list(date_time_format.lang_config[self.lang]['month'].values())
        if self.weekdays is None or self.months is None:
            self.log.error("Error! weekdays:%s, months:%s" % (self.weekdays, self.months))

        self.skill_control.states = {
                'inactive':[
                    'handle_wake_me',
                    'handle_set_alarm',
                    'handle_status',
                    'handle_delete',
                    'change.alarm.sound.intent'
                    ],
                'active':['handle_delete', 'snooze'],
                'wait_reply':[],
                'wait_confirm':[]
                }
        self.skill_control.state = 'inactive'


    # TODO: remove the "private.mycroftai.has_alarm" event in favor of the
    #   "skill.alarm.query-active" event.
    def on_has_alarm(self, message):
        """Reply to requests for alarm on/off status."""
        total = len(self.settings["alarm"])
        self.bus.emit(message.response(data={"active_alarms": total}))

    def handle_active_alarm_query(self, message):
        """Emits an event indicating whether or not there are any active alarms.

        In this case, an "active alarm" is defined as any alarms that exist for a time
        in the future.
        """
        event_data = {"active_alarms": bool(self.settings["alarm"])}
        event = message.response(data=event_data)
        self.bus.emit(event)

    def set_alarm(self, when, name=None, repeat=None):
        """Set an alarm at the specified datetime."""

        requested_time = when.replace(second=0, microsecond=0)
        if repeat:
            alarm = create_recurring_rule(requested_time, repeat)
            alarm = {
                "timestamp": alarm["timestamp"],
                "repeat_rule": alarm["repeat_rule"],
                "name": name or "",
            }
        else:
            alarm = {
                "timestamp": to_utc(requested_time).timestamp(),
                "repeat_rule": "",
                "name": name or "",
            }

        for existing in self.settings["alarm"]:
            if alarm == existing:
                self.speak_dialog("alarm.already.exists")
                return None
        self.settings["alarm"].append(alarm)
        self._schedule()
        return alarm

    def _schedule(self):
        """Schedule future event for an alarm and clean up as required."""
        # cancel any existing timed event
        self.cancel_scheduled_event("NextAlarm")
        self.settings["alarm"] = curate_alarms(self.settings["alarm"])

        # set timed event for next alarm (if it exists)
        if self.settings["alarm"]:
            alarm_dt = get_alarm_local(self.settings["alarm"][0])
            self.schedule_event(
                self._alarm_expired, to_system(alarm_dt), name="NextAlarm"
            )
        event_data = {"active_alarms": bool(self.settings["alarm"])}
        event = Message("skill.alarm.scheduled", data=event_data)
        self.bus.emit(event)

    def _get_recurrence(self, utterance: str):
        """Get recurrence pattern from user utterance."""
        recur = create_day_set(utterance, self.recurrence_dict)
        while not recur:
            response = self.get_response("query.recurrence", num_retries=1)
            if not response:
                return
            recur = create_day_set(response, self.recurrence_dict)

        # TODO: remove days following an "except" in the utt
        if self.voc_match(utterance, "Except"):
            # TODO: Support exceptions
            self.speak_dialog("no.exceptions.yet")
            return

        return recur

    def _verify_alarm_time(self, when, today, recur):
        """Verify time when creating an alarm."""
        alarm_time = when
        confirmed_time = False
        while (not when or when == today) and not confirmed_time:
            if recur:
                alarm_nice_time = nice_time(alarm_time, use_ampm=True)
                recur_description = describe_recurrence(
                    recur, self.recurrence_dict, self.translate("and")
                )
                conf = self.ask_yesno(
                    "confirm.recurring.alarm",
                    data={"time": alarm_nice_time, "recurrence": recur_description},
                )
            else:
                alarm_nice_dt = nice_date_time(alarm_time, now=today, use_ampm=True)
                conf = self.ask_yesno("confirm.alarm", data={"time": alarm_nice_dt})
            if not conf:
                return
            if conf == "yes":
                when = [alarm_time]
                confirmed_time = True
            else:
                # check if a new (corrected) time was given
                when = extract_datetime(conf)
                if when is not None:
                    when = when[0]
                if not when or when == today:
                    # Not a confirmation and no date/time in statement, quit
                    return
                alarm_time = when
                when = None  # reverify
        return alarm_time, confirmed_time

    # Wake me on ... (hard to match with Adapt entities)
    @intent_handler(
        IntentBuilder("")
        .require("WakeMe")
        .optionally("Recurring")
        .optionally("Recurrence")
    )
    def handle_wake_me(self, message):
        """Handler for "wake me at..."""
        self.handle_set_alarm(message)

    @intent_handler(
        IntentBuilder("")
        .require("Alarm")
        .optionally("Recurring")
        .optionally("Recurrence")
    )
    def handle_set_alarm(self, message):
        """Handler for "set an alarm for..."""
        self.change_state('active')
        utt = message.data.get("utterance").lower()
        recur = None

        if message.data.get("Recurring"):
            # Just ignoring the 'Recurrence' now, we support more complex stuff
            # recurrence = message.data.get('Recurrence')
            recur = self._get_recurrence(utt)

        # Get the time
        when, utt_no_datetime = extract_datetime(utt) or (None, utt)

        # Get name from leftover string from extract_datetime
        name = self._get_alarm_name(utt_no_datetime)

        # Will return dt of unmatched string
        today = extract_datetime("today", lang="en-us")[0]

        # Check the time if it's midnight. This is to check if the user
        # said a recurring alarm with only the Day or if the user did
        # specify to set an alarm on midnight. If it's confirmed that
        # it's for a day only, then get another response from the user
        # to clarify what time on that day the recurring alarm is.
        is_midnight = utterance_has_midnight(
            utt, when, self.THRESHOLD, self.translate_list("midnight")
        )

        if (when is None or when.time() == today.time()) and not is_midnight:
            response = self.get_response("query.for.when", validator=extract_datetime)
            if not response:
                self.speak_dialog("alarm.schedule.cancelled")
                self.change_state('inactive')
                return
            when_temp = extract_datetime(response)
            if when_temp is not None:
                when_temp = when_temp[0]
                # TODO add check for midnight
                # is_midnight = utterance_has_midnight(response, when_temp, self.THRESHOLD,
                #                                      self.translate_list("midnight"))
                when = (
                    when_temp
                    if when is None
                    else datetime(
                        tzinfo=when.tzinfo,
                        year=when.year,
                        month=when.month,
                        day=when.day,
                        hour=when_temp.hour,
                        minute=when_temp.minute,
                    )
                )
            else:
                when = None

        verified_alarm = self._verify_alarm_time(when, today, recur)
        if verified_alarm is None:
            self.change_state('inactive')
            return
        alarm_time, confirmed_time = verified_alarm

        alarm = {}
        if not recur:
            alarm_time_ts = to_utc(alarm_time).timestamp()
            now_ts = now_utc().timestamp()
            if alarm_time_ts > now_ts:
                alarm = self.set_alarm(alarm_time, name)
            else:
                if self.translate("today") in utt or self.translate("tonight") in utt:
                    self.speak_dialog("alarm.past")
                    self.change_state('inactive')
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
            self.change_state('inactive')
            return

        # Don't want to hide the animation
        self.enclosure.deactivate_mouth_events()
        if confirmed_time:
            self.speak_dialog("alarm.scheduled")
        else:
            alarm_nice_time = self._describe(alarm)
            reltime = nice_relative_time(get_alarm_local(alarm))
            if recur:
                self.speak_dialog(
                    "recurring.alarm.scheduled.for.time",
                    data={"time": alarm_nice_time, "rel": reltime},
                )
            else:
                self.speak_dialog(
                    "alarm.scheduled.for.time",
                    data={"time": alarm_nice_time, "rel": reltime},
                )

        self._show_alarm_ui(alarm_time, name)
        self._show_alarm_anim(alarm_time)
        self.enclosure.activate_mouth_events()
        self.change_state('inactive')

    def _get_alarm_name(self, utt):
        """Get the alarm name using regex on an utterance."""
        self.log.debug("Utterance being searched: " + utt)
        invalid_names = self.translate_list("invalid_names")
        rx_file = self.find_resource("name.rx", "regex")
        if utt and rx_file:
            patterns = []
            with open(rx_file) as regex_file:
                patterns = [
                    p.strip()
                    for p in regex_file.readlines()
                    if not p.strip().startswith("#")
                ]

            for pat in patterns:
                self.log.debug("Regex pattern: {}".format(pat))
                res = re.search(pat, utt)
                if res:
                    try:
                        name = res.group("Name").strip()
                        self.log.debug("Regex name extracted: {}".format(name))
                        if name and len(name.strip()) > 0 and name not in invalid_names:
                            return name.lower()
                    except IndexError:
                        pass
        return ""

    @property
    def use_24hour(self):
        """Whether 24 hour time format should be used."""
        return self.config_core.get("time_format") == "full"

    def _describe(self, alarm):
        """Describe the given alarm in a human expressable format."""
        if alarm["repeat_rule"]:
            # Describe repeating alarms
            if alarm["repeat_rule"].startswith("FREQ=WEEKLY;INTERVAL=1;BYDAY="):
                recur_description = describe_repeat_rule(
                    alarm["repeat_rule"], self.recurrence_dict, self.translate("and")
                )
            else:
                recur_description = self.translate("repeats")

            alarm_dt = get_alarm_local(alarm)

            dialog = "recurring.alarm"
            if alarm["name"] != "":
                dialog = dialog + ".named"
            return self.translate(
                dialog,
                data={
                    "time": nice_time(alarm_dt, use_ampm=True),
                    "recurrence": recur_description,
                    "name": alarm["name"],
                },
            )
        else:
            alarm_dt = get_alarm_local(alarm)
            dt_string = nice_date_time(alarm_dt, now=now_local(), use_ampm=True)
            if alarm["name"]:
                return self.translate(
                    "alarm.named", data={"datetime": dt_string, "name": alarm["name"]}
                )
            else:
                return dt_string

    @intent_handler(
        IntentBuilder("")
        .require("Query")
        .optionally("Next")
        .require("Alarm")
        .optionally("Recurring")
    )
    def handle_status(self, message):
        """Respond to request for alarm status."""

        utt = message.data.get("utterance")

        if len(self.settings["alarm"]) == 0:
            self.speak_dialog("alarms.list.empty")
            return

        status, alarms = self._get_alarm_matches(
            utt,
            alarm=self.settings["alarm"],
            max_results=3,
            dialog="ask.which.alarm",
            is_response=False,
        )
        total = None
        desc = []
        if alarms:
            total = len(alarms)
            for alarm in alarms:
                desc.append(self._describe(alarm))

        items_string = ""
        if desc:
            items_string = join_list(desc, self.translate("and"))

        if status == "No Match Found":
            self.speak_dialog("alarm.not.found")
        elif status == "User Cancelled":
            return
        elif status == "Next":
            reltime = nice_relative_time(get_alarm_local(alarms[0]))

            self.speak_dialog(
                "next.alarm",
                data={"when": self._describe(alarms[0]), "duration": reltime},
            )
        else:
            if total == 1:
                reltime = nice_relative_time(get_alarm_local(alarms[0]))
                self.speak_dialog(
                    "alarms.list.single", data={"item": desc[0], "duration": reltime}
                )
            else:
                self.speak_dialog(
                    "alarms.list.multi", data={"count": total, "items": items_string}
                )

    def _get_alarm_matches(
        self,
        utt,
        alarm=None,
        max_results=1,
        dialog="ask.which.alarm",
        is_response=False,
    ):
        """Get list of alarms that match based on a user utterance.
        Arguments:
            utt (str): string spoken by the user
            alarm (list): list of alarm to match against
            max_results (int): max number of results desired
            dialog (str): name of dialog file used for disambiguation
            is_response (bool): is this being called by get_response
        Returns:
            (str): ["All", "Matched", "No Match Found", or "User Cancelled"]
            (list): list of matched alarm
        """
        alarms = alarm or self.settings["alarm"]
        all_words = self.translate_list("all")
        next_words = self.translate_list("next")
        status = ["All", "Matched", "No Match Found", "User Cancelled", "Next"]

        # No alarms
        if alarms is None or len(alarms) == 0:
            self.log.info("Cannot get match. No active alarms.")
            return (status[2], None)

        # Extract Alarm Time
        when, utt_no_datetime = extract_datetime(utt) or (None, None)

        # Will return dt of unmatched string
        today = extract_datetime("today", lang="en-us")[0]

        # Check the time if it's midnight. This is to check if the user
        # said a recurring alarm with only the Day or if the user did
        # specify to set an alarm on midnight. If it's confirmed that
        # it's for a day only, then get another response from the user
        # to clarify what time on that day the recurring alarm is.
        is_midnight = utterance_has_midnight(
            utt, when, self.THRESHOLD, self.translate_list("midnight")
        )

        if when == today and not is_midnight:
            when = None

        time_matches = None
        time_alarm = None
        if when:
            time_alarm = to_utc(when).timestamp()
            if is_midnight:
                time_alarm = time_alarm + 86400.0

            time_matches = [a for a in alarms if abs(a["timestamp"] - time_alarm) <= 60]

        # add other categories of alarm matches here
        utt = self.workaround_lingua_franca(utt)
        when, utt_no_datetime = extract_datetime(utt) or (None, utt)

        when_utc = None if when is None else to_utc(when)

        have_time = False
        if when_utc:
            user_time = when.strftime("%H:%M:%S")
            if user_time == "00:00:00" and self.voc_match(utt, "Midnight"):
                have_time = True
            if user_time != "00:00:00":
                have_time = True

        user_dow = self.get_dow_from_utterance(utt)

        advanced_matches = self.get_advanced_matches(utt, have_time, when, when_utc, user_dow, alarms)

        # Extract Recurrence
        recur = None
        recurrence_matches = None
        for word in self.recurrence_dict:
            is_match = fuzzy_match(word, utt.lower(), self.THRESHOLD)
            if is_match:
                recur = create_day_set(utt, self.recurrence_dict)
                alarm_recur = create_recurring_rule(when, recur)
                recurrence_matches = [
                    a for a in alarms if a["repeat_rule"] == alarm_recur["repeat_rule"]
                ]
                break

        utt = utt_no_datetime or utt

        # Extract Ordinal/Cardinal Numbers
        number = extract_number(utt, ordinals=True)
        if number and number > 0:
            number = int(number)
        else:
            number = None

        # Extract Name
        name_matches = [
            a
            for a in alarms
            if a["name"] and fuzzy_match(a["name"], utt, self.THRESHOLD)
        ]

        # Match Everything
        alarm_to_match = None
        if when:
            if recur:
                alarm_to_match = alarm_recur
            else:
                alarm_to_match = {"timestamp": time_alarm, "repeat_rule": ""}

        # Find the Intersection of the Alarms list and all the matched alarms
        orig_count = len(alarms)
        if len(advanced_matches) > 0:
            alarms = advanced_matches
        if when and time_matches:
            alarms = [a for a in alarms if a in time_matches]
        if recur and recurrence_matches:
            alarms = [a for a in alarms if a in recurrence_matches]
        if name_matches:
            alarms = [a for a in alarms if a in name_matches]

        # Utterance refers to all alarms
        if utt and any(fuzzy_match(i, utt, 1) for i in all_words):
            return (status[0], alarms)
        # Utterance refers to the next alarm to go off
        elif utt and any(fuzzy_match(i, utt, 1) for i in next_words):
            return (status[4], [alarms[0]])

        if max_results < orig_count and len(alarms) == max_results:
            # if we started with more than we have
            # and that's how many we asked for
            return (status[1], alarms)

        # Given something to match but no match found
        if (
            (number and number > len(alarms))
            or (recur and not recurrence_matches)
            or (when and not time_matches)
        ):
            return (status[2], None)
        # If number of alarms filtered were the same,
        # assume user asked for ALL alarms
        if (
            len(alarms) == orig_count
            and max_results > 1
            and not number
            and not when
            and not recur
        ):
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

            items_string = ""
            if desc:
                items_string = join_list(desc, self.translate("and"))

            self.log.debug("Too many alarms, ask for clarification")
            reply = self.get_response(
                dialog,
                data={
                    "number": len(alarms),
                    "list": items_string,
                },
                num_retries=1,
            )

            if reply:
                # if user wants to bail, bail!
                if self.voc_match(utt, "Terminate"):
                    self.log.debug("user cancels the select request")
                    return (status[3], None)

                return self._get_alarm_matches(
                    reply,
                    alarm=alarms,
                    max_results=max_results,
                    dialog=dialog,
                    is_response=True,
                )
            else:
                return (status[3], None)

        # No matches found
        return (status[2], None)

    # sometimes LF returns a roman numeral for
    # a number so the 26th will return xxvi
    def roman_to_int(self, s):
        rom_val = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
        int_val = 0
        for i in range(len(s)):
            if i > 0 and rom_val[s[i]] > rom_val[s[i - 1]]:
                int_val += rom_val[s[i]] - 2 * rom_val[s[i - 1]]
            else:
                int_val += rom_val[s[i]]
        return int_val

    def get_advanced_matches(self, utt, have_time, when, when_utc, user_dow, alarm_list):
        '''see if we have any of the following
           in order of preference
           exact matches
           date matches
           time of day matches (tod)
           day of week matches (dow)
           day of month matches (dom)
        '''
        # holds exact date and time matches
        exact_matches = []
        dom = None
        try:
            dom = self.roman_to_int(utt)
        except:
            self.log.debug("Not a roman numeral")

        if dom is None:
            dom = extract_number(utt)

        # if the user says a day of the week (mon-sun) we
        # keep them in a separate list of day of week matches
        dow_matches = []

        # we also look for specific time matches like 9am
        tod_matches = []
        if when_utc:
            tod_matches = self.get_tod_matches(when.time(), alarm_list)

        # these alarms match our when_utc date only
        date_matches = []

        # these alarms match any numbers passed in like
        # the 25th, 5 etc which we assume are dom
        # hopefully this won't muss up ordinals
        dom_matches = []

        for alm in alarm_list:
            self.log.debug("    Loop: %s" % (alm,))

            # get utc time from alarm timestamp
            dt_obj = datetime.fromtimestamp( alm['timestamp'] )
            dt_obj = dt_obj.astimezone(pytz.utc)

            # we also need a local version of our utc time
            cfg_tz = pytz.timezone(self.local_tz)
            dt_local = dt_obj.astimezone(cfg_tz)

            if user_dow == dt_local.weekday():
                dow_matches.append(alm)

            if dom == dt_local.day:
                dom_matches.append(alm)

            if have_time:
                # unambiguous
                if when_utc == dt_obj:
                    exact_matches.append(alm)
            else:
                self.log.debug("    Loop: when:%s, dt_obj:%s" % (when_utc, dt_obj))
                if when_utc is not None and dt_obj is not None:
                    # do dates match ?
                    if when_utc.strftime("%y-%m-%d") == dt_obj.strftime("%y-%m-%d"):
                        date_matches.append(alm)

        if len(exact_matches) > 0:
            return exact_matches

        if len(date_matches) > 0:
            return date_matches

        if len(tod_matches) > 0:
            return tod_matches

        if len(dow_matches) > 0:
            return dow_matches

        return dom_matches

    def get_tod_matches(self, alarm_time, alarm_list):
        ''' find alarms where the time matches'''
        tod_matches = []

        for alarm in alarm_list:
            # get utc time from alarm timestamp
            dt_obj = datetime.fromtimestamp( alarm['timestamp'] )
            dt_obj = dt_obj.astimezone(pytz.utc)

            # we also need a local version of our utc time
            cfg_tz = pytz.timezone(self.local_tz)
            dt_local = dt_obj.astimezone(cfg_tz)

            self.log.debug("Check for TOD matches, dt_local.time()=%s" % (dt_local.time(),))
            if dt_local.time() == alarm_time:
                tod_matches.append(alarm)

        return tod_matches

    def get_dow_from_utterance(self, utt):
        user_dow = None
        result = re.findall('(mon|tues|wed|thurs|fri|sat|sun)day', utt)
        if result:
            utt_dow = result[0] + 'day'
            user_dow = self.weekdays.index(utt_dow) if utt_dow in self.weekdays else None
        return user_dow

    def workaround_lingua_franca(self, utt):
        # Lingua-franca workaround - day of
        # week and date confuses LF terribly.
        # if a day of the week (monday, friday,
        # etc) is included with a valid date
        # like "monday april 5th" LF will
        # return bad data so we make sure
        # we never include both. "monday
        # april 5th" becomes "april 5th".

        for month in self.months:
            if utt.find(month) > -1 and re.search(r'\d+', utt):
                # if we have a month and a number/day
                # whack any days of week terms
                for day in self.weekdays:
                    utt = utt.replace(day,'')

        return utt

    @intent_handler(
        IntentBuilder("")
        .require("Delete")
        .require("Alarm")
        .optionally("Recurring")
        .optionally("Recurrence")
    )
    def handle_delete(self, message):
        """Respond to request to remove a scheduled alarm."""
        self.change_state('active')
        if has_expired_alarm(self.settings["alarm"]):
            self._stop_expired_alarm()
            return

        total = len(self.settings["alarm"])
        if not total:
            self.speak_dialog("alarms.list.empty")
            self.change_state('inactive')
            return

        utt = message.data.get("utterance") or ""

        status, alarms = self._get_alarm_matches(
            utt,
            alarm=self.settings["alarm"],
            max_results=1,
            dialog="ask.which.alarm.delete",
            is_response=False,
        )


        if status == "User Cancelled":
            self.speak_dialog("alarm.delete.cancelled")
            self.change_state('inactive')
            return

        if alarms:
            total = len(alarms)
        else:
            total = None

        if total == 1:
            desc = self._describe(alarms[0])
            recurring = ".recurring" if alarms[0]["repeat_rule"] else ""

            if (
                self.ask_yesno("ask.cancel.desc.alarm" + recurring, data={"desc": desc})
                == "yes"
            ):
                del self.settings["alarm"][self.settings["alarm"].index(alarms[0])]
                self._schedule()
                self.speak_dialog(
                    "alarm.cancelled.desc" + recurring, data={"desc": desc}
                )
                self.change_state('inactive')
                self.gui.release()
                return
            else:
                self.speak_dialog("alarm.delete.cancelled")
                # As the user did not confirm to delete
                # return True to skip all the remaining conditions
                self.change_state('inactive')
                return
        elif status in ["Next", "All", "Matched"]:
            if (
                self.ask_yesno("ask.cancel.alarm.plural", data={"count": total})
                == "yes"
            ):
                self.settings["alarm"] = [
                    a for a in self.settings["alarm"] if a not in alarms
                ]
                self._schedule()
                self.change_state('inactive')
                self.speak_dialog("alarm.cancelled.multi", data={"count": total})
                self.gui.release()
            return
        elif not total:
            # Failed to delete
            self.change_state('inactive')
            self.speak_dialog("alarm.not.found")

        return

    #@intent_handler("snooze.intent")
    @intent_handler(IntentBuilder("snooze").optionally("Snooze"))
    def snooze_alarm(self, message):
        """Snooze an expired alarm for the requested time.

        If no time provided by user, defaults to 9 mins.
        """
        if not has_expired_alarm(self.settings["alarm"]):
            return

        self.cancel_scheduled_event("Beep")
        self.cancel_scheduled_event("NextAlarm")

        self.__end_beep()
        self.__end_flash()

        utt = message.data.get("utterance") or ""
        snooze_for = extract_number(utt[0])
        if not snooze_for or snooze_for < 1:
            snooze_for = 9  # default to 9 minutes

        # Snooze always applies the the first alarm in the sorted array
        alarm = self.settings["alarm"][0]
        alarm_dt = get_alarm_local(alarm)
        snooze = to_utc(alarm_dt) + timedelta(minutes=snooze_for)

        if "snooze" in alarm:
            # already snoozed
            original_time = alarm["snooze"]
        else:
            original_time = alarm["timestamp"]

        # Fill schedule with a snoozed entry -- 3 items:
        #    snooze_expire_timestamp, repeat_rule, original_timestamp
        self.settings["alarm"][0] = {
            "timestamp": snooze.timestamp(),
            "repeat_rule": alarm["repeat_rule"],
            "name": alarm["name"],
            "snooze": original_time,
        }
        self._schedule()

    @intent_handler("change.alarm.sound.intent")
    def handle_change_alarm(self, _):
        """Handler for requests to change the alarm sound.

        Note: This functionality is not yet supported. Directs users to Skill
        settings on home.mycroft.ai.
        """
        self.speak_dialog("alarm.change.sound")

    ##########################################################################
    # Audio and Device Feedback

    def converse(self, utterances, lang="en-us"):
        """While an alarm is expired, check all utterances for Stop vocab."""
        self.log.debug("Enter AlarmSkill converse utt:%s" % (utterances,))
        if has_expired_alarm(self.settings["alarm"]) and utterances:
            self.log.debug("AlarmSkill will consume the utterance")
            if utterances and self.voc_match(utterances[0], "StopBeeping"):
                self._stop_expired_alarm()
            elif self.voc_match(utterances[0], "Snooze"):
                message = Message(
                  "internal.snooze",
                  data=dict(utterance=utterances)
                  )
                self.snooze_alarm(message)
            else:
                self.log.info("AlarmSkill:Converse confused by %s" % (utterances[0],))
                self.log.debug("AlarmSkill will NOT consume the utterance")
                return False  # don't consume this phrase

            return True  # consume this phrase
        self.log.debug("AlarmSkill will NOT consume the utterance")

    def stop(self, _=None):
        """Respond to system stop commands."""
        if has_expired_alarm(self.settings["alarm"]):
            self._stop_expired_alarm()
            return True  # Stop signal handled no need to listen
        else:
            return False

    def _play_beep(self, _=None):
        """ Play alarm sound file """

        now = now_local()

        self.bus.emit(Message("mycroft.alarm.beeping", data=dict(time=now.strftime("%m/%d/%Y, %H:%M:%S"))))

        if not self.beep_start_time:
            self.beep_start_time = now
        elif (now - self.beep_start_time).total_seconds() > self.settings[
            "max_alarm_secs"
        ]:
            # alarm has been running long enough, auto-quiet it
            self.log.info("Automatically quieted alarm after 10 minutes")
            self._stop_expired_alarm()
            return

        # Validate user-selected alarm sound file
        alarm_file = join(
            abspath(dirname(__file__)), "sounds", self.sound_name + ".mp3"
        )
        if not isfile(alarm_file):
            # Couldn't find the required sound file
            self.sound_name = self.DEFAULT_SOUND
            alarm_file = join(
                abspath(dirname(__file__)), "sounds", self.sound_name + ".mp3"
            )

        beep_duration = self.sounds[self.sound_name]
        repeat_interval = beep_duration + self.BEEP_GAP

        next_beep = now + timedelta(seconds=repeat_interval)

        self.cancel_scheduled_event("Beep")
        self.schedule_event(self._play_beep, to_system(next_beep), name="Beep")

        # Increase volume each pass until fully on
        if self.saved_volume:
            if self.volume < 90:
                self.volume += 10
            self.mixer.setvolume(self.volume)

        try:
            self.beep_process = play_mp3(alarm_file)
        except Exception:
            self.beep_process = None

    def _while_beeping(self, message):
        if self.flash_state < 3:
            if self.flash_state == 0:
                alarm_timestamp = message.data["alarm_time"]
                alarm_dt = get_alarm_local(timestamp=alarm_timestamp)
                self._render_time(alarm_dt)
            self.flash_state += 1
        else:
            self.enclosure.mouth_reset()
            self.flash_state = 0

        # Check if the WAV is still playing
        if self.beep_process:
            self.beep_process.poll()
            if self.beep_process.returncode:
                # The playback has ended
                self.beep_process = None

    def __end_beep(self):
        self.cancel_scheduled_event("Beep")
        self.beep_start_time = None
        if self.beep_process:
            try:
                if self.beep_process.poll() is None:  # still running
                    self.beep_process.kill()
            except Exception:
                pass
            self.beep_process = None
        self._restore_volume()

    def _stop_expired_alarm(self):
        if has_expired_alarm(self.settings["alarm"]):
            self.__end_beep()
            self.__end_flash()
            self.cancel_scheduled_event("NextAlarm")

            self.settings["alarm"] = curate_alarms(
                self.settings["alarm"], 0
            )  # end any expired alarm
            self.gui.release()
            self._schedule()
            self.change_state('inactive')
            return True
        else:
            return False

    def _restore_volume(self):
        """Return global volume to the appropriate level if we've messed with it."""
        if self.saved_volume:
            self.mixer.setvolume(self.saved_volume[0])
            self.saved_volume = None

    def _alarm_expired(self):
        self.change_state('active')
        self.sound_name = self.settings["sound"]  # user-selected alarm sound
        if not self.sound_name or self.sound_name not in self.sounds:
            # invalid sound name, use the default
            self.sound_name = self.DEFAULT_SOUND

        if self.settings["start_quiet"] and self.mixer:
            if not self.saved_volume:  # don't overwrite if already saved!
                self.saved_volume = self.mixer.getvolume()
                self.volume = 0  # increase by 10% each pass
        else:
            self.saved_volume = None

        self._play_beep()

        # Once a second Flash the alarm and auto-listen
        self.flash_state = 0
        self.enclosure.deactivate_mouth_events()
        alarm = self.settings["alarm"][0]
        self.schedule_repeating_event(
            self._while_beeping,
            0,
            1,
            name="Flash",
            data={"alarm_time": alarm["timestamp"]},
        )
        alarm_timestamp = alarm.get("timestamp", "")
        alarm_dt = get_alarm_local(timestamp=alarm_timestamp)
        alarm_name = alarm.get("name", "")
        self._show_alarm_ui(alarm_dt, alarm_name, alarm_exp=True)

    def __end_flash(self):
        self.cancel_scheduled_event("Flash")
        self.enclosure.mouth_reset()
        self.enclosure.activate_mouth_events()

    def _show_alarm_anim(self, alarm_dt):
        """Animated confirmation of the alarm."""
        self.enclosure.mouth_reset()

        self._render_time(alarm_dt)
        time.sleep(2)
        self.enclosure.mouth_reset()

        # Show an animation
        # TODO: mouth_display_png() is choking images > 8x8
        #       (likely on the enclosure side)
        for i in range(1, 16):
            png = join(
                abspath(dirname(__file__)), "anim", "Alarm-" + str(int(i)) + "-1.png"
            )
            # self.enclosure.mouth_display_png(png, x=0, y=0, refresh=False,
            #                                  invert=True)
            png = join(
                abspath(dirname(__file__)), "anim", "Alarm-" + str(int(i)) + "-2.png"
            )
            if i < 8:
                self.enclosure.mouth_display_png(
                    png, x=8, y=0, refresh=False, invert=True
                )
            png = join(
                abspath(dirname(__file__)), "anim", "Alarm-" + str(int(i)) + "-3.png"
            )
            self.enclosure.mouth_display_png(png, x=16, y=0, refresh=False, invert=True)
            png = join(
                abspath(dirname(__file__)), "anim", "Alarm-" + str(int(i)) + "-4.png"
            )
            self.enclosure.mouth_display_png(png, x=24, y=0, refresh=False, invert=True)

            if i == 4:
                time.sleep(1)
            else:
                time.sleep(0.15)
        self.enclosure.mouth_reset()

    def _render_time(self, alarm_dt):
        """Show the time in numbers eg '8:00 AM'."""
        timestr = nice_time(
            alarm_dt, speech=False, use_ampm=True, use_24hour=self.use_24hour
        )
        x = 16 - ((len(timestr) * 4) // 2)  # centers on display
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
            elif ch == "A" or ch == "P" or ch == "M":
                png = ch + ".png"
                w = 5
            else:
                png = ch + ".png"
                w = 4

            png = join(abspath(dirname(__file__)), "anim", png)
            self.enclosure.mouth_display_png(png, x=x, y=2, refresh=False)
            x += w

    def _show_alarm_ui(self, alarm_dt, alarm_name, alarm_exp=False):
        self.gui["alarmTime"] = nice_time(alarm_dt, speech=False,
                                          use_ampm=True)
        self.gui["alarmName"] = alarm_name.title()
        self.gui["alarmExpired"] = alarm_exp
        override_idle = True if alarm_exp else False
        self.gui.show_page("alarm.qml", override_idle=override_idle)

    ##########################################################################
    # Public Skill API Methods

    @skill_api_method
    def delete_all_alarms(self):
        """Delete all stored alarms."""
        if len(self.settings["alarm"]) > 0:
            self.settings["alarm"] = []
            self._schedule()
            return True
        else:
            return False

    @skill_api_method
    def get_active_alarms(self):
        """Get list of active alarms.

        This includes any alarms that are in an expired state.

        Returns:
            List of alarms as Objects: {
                "timestamp" (float): POSIX timestamp of next alarm expiry
                "repeat_rule" (str): iCal repeat rule
                "name" (str): Alarm name
                "snooze" (float): [optional] POSIX timestamp if alarm was snoozed
            }
        """
        return self.settings["alarm"]

    @skill_api_method
    def is_alarm_expired(self):
        """Check if an alarm is currently expired and beeping."""
        return has_expired_alarm(self.settings["alarm"])


def create_skill():
    """Create the Alarm Skill for Mycroft."""
    return AlarmSkill()
