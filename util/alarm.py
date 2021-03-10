# Copyright 2021 Mycroft AI Inc.
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

from datetime import datetime, timedelta
from dateutil.rrule import rrulestr

from mycroft.util import LOG
from mycroft.util.time import to_utc, now_utc


def create_recurring_rule(when, recur):
    """Create a recurring iCal rrule for an alarm.

    Arguments:
        recur (set): day index strings, e.g. {"3", "4"}
    Returns:
        {
            "timestamp" (datetime.timestamp): next occurence of alarm,
            "repeat_rule" (rrule): iCal repeat rule
        }
    # TODO: Support more complex alarms, e.g. first monday, monthly, etc
    """
    rule = ""
    abbr = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]
    days = []
    for day in recur:
        days.append(abbr[int(day)])
    if days:
        rule = "FREQ=WEEKLY;INTERVAL=1;BYDAY=" + ",".join(days)

    if when and rule:
        when = to_utc(when)

        # Create a repeating rule that starts in the past, enough days
        # back that it encompasses any repeat.
        past = when + timedelta(days=-45)
        repeat_rule = rrulestr("RRULE:" + rule, dtstart=past)
        now = to_utc(now_utc())
        # Get the first repeat that happens after right now
        next_occurence = repeat_rule.after(now)
        return {
            "timestamp": to_utc(next_occurence).timestamp(),
            "repeat_rule": rule,
        }
    else:
        return {
            "timestamp": None,
            "repeat_rule": rule,
        }

def curate_alarms(alarms, curation_limit=1):
    """Clean a list of alarms including rescheduling repeating alarms.

    Arguments:
        alarms (List): list of Alarms
        curation_limit (int, optional): Seconds past expired at which to 
                                        remove the alarm
    Returns:
        List: cleaned list of Alarms
    """
    curated_alarms = []
    now_ts = to_utc(now_utc()).timestamp()

    for alarm in alarms:
        # Alarm format == [timestamp, repeat_rule[, orig_alarm_timestamp]]
        if alarm["timestamp"] < now_ts:
            if alarm["timestamp"] < (now_ts - curation_limit):
                # skip playing an old alarm
                if alarm["repeat_rule"]:
                    # reschedule in future if repeat rule exists
                    curated_alarms.append(get_next_repeat(alarm))
            else:
                # schedule for right now, with the
                # third entry as the original base time
                base = alarm["name"] if alarm["name"] == "" else alarm["timestamp"]
                curated_alarms.append(
                    {
                        "timestamp": now_ts + 1,
                        "repeat_rule": alarm["repeat_rule"],
                        "name": alarm["name"],
                        "snooze": base,
                    }
                )
        else:
            curated_alarms.append(alarm)

    curated_alarms = sorted(curated_alarms, key=lambda a: a["timestamp"])
    return curated_alarms


def get_next_repeat(alarm):
    """Get the next occurence of a repeating alarm.

    Arguments:
        alarm (Alarm): a repeating alarm
    Returns:
        {
            "timestamp" (datetime.timestamp): next occurence of alarm,
            "repeat_rule" (rrule): iCal repeat rule,
            "name" (Str): name of alarm
        }
    """
    # evaluate recurrence to the next instance
    if "snooze" in alarm:
        # repeat from original time (it was snoozed)
        ref = datetime.fromtimestamp(alarm["repeat_rule"])
    else:
        ref = datetime.fromtimestamp(alarm["timestamp"])

    # Create a repeat rule and get the next alarm occurrance after that
    start = to_utc(ref)
    repeat_rule = rrulestr("RRULE:" + alarm["repeat_rule"], dtstart=start)
    now = to_utc(now_utc())
    next_occurence = repeat_rule.after(now)

    LOG.debug("     Now={}".format(now))
    LOG.debug("Original={}".format(start))
    LOG.debug("    Next={}".format(next_occurence))

    return {
        "timestamp": to_utc(next_occurence).timestamp(),
        "repeat_rule": alarm["repeat_rule"],
        "name": alarm["name"],
    }