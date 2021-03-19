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

from datetime import datetime
from dateutil.rrule import rrulestr

from mycroft.util import LOG
from mycroft.util.format import nice_time, nice_date
from mycroft.util.time import default_timezone, now_local, now_utc, to_local, to_utc


def alarm_log_dump(alarms, tag=""):
    """Create a log dump of all alarms. Useful when debugging."""
    dump = "\n" + "=" * 30 + " ALARMS " + tag + " " + "=" * 30 + "\n"
    dump += "raw = " + str(alarms) + "\n\n"

    now_ts = to_utc(now_utc()).timestamp()
    dt = datetime.fromtimestamp(now_ts)
    dump += "now = {} ({})\n".format(
        nice_time(get_alarm_local(timestamp=now_ts), speech=False, use_ampm=True),
        now_ts,
    )
    dump += "      U{} L{}\n".format(to_utc(dt), to_local(dt))
    dump += "\n\n"

    idx = 0
    for alarm in alarms:
        dt = get_alarm_local(alarm)
        dump += "alarm[{}] - {} \n".format(idx, alarm)
        dump += "           Next: {} {}\n".format(
            nice_time(dt, speech=False, use_ampm=True),
            nice_date(dt, now=now_local()),
        )
        dump += "                 U{} L{}\n".format(dt, to_local(dt))
        if "snooze" in alarm:
            dtOrig = get_alarm_local(timestamp=alarm["snooze"])
            dump += "           Orig: {} {}\n".format(
                nice_time(dtOrig, speech=False, use_ampm=True),
                nice_date(dtOrig, now=now_local()),
            )
        idx += 1

    dump += "=" * 75

    return dump

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

def get_alarm_local(alarm=None, timestamp=None):
    """Get the local time of an Alarm or timestamp.

    Arguments:
        alarm (Alarm): single instance of an Alarm
        timestamp (datetime.timestamp): 
    Returns:
        datetime.timestamp
    """
    # TODO should this be two separate functions?
    if alarm is None and timestamp is None:
        return None
    if timestamp:
        ts = timestamp
    else:
        ts = alarm["timestamp"]

    return datetime.fromtimestamp(ts, default_timezone())

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

def has_expired_alarm(alarms):
    """Check if list of alarms includes one that is currently expired.
    
    Arguments:
        alarms (List): list of Alarms
    Returns:
        Bool: True if an alarm should be 'going off' now.
              Snoozed alarms don't count until they are triggered again.
    """
    if len(alarms) < 1:
        return False

    now_ts = to_utc(now_utc()).timestamp()
    for alarm in alarms:
        if alarm["timestamp"] <= now_ts:
            return True

    return False
