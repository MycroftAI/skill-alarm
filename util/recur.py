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

from datetime import timedelta
from dateutil.rrule import rrulestr

from mycroft.util.format import join_list
from mycroft.util.time import now_utc, to_utc


def create_day_set(phrase, recurrence_dict):
    """Create a Set of recurrence days from utterance.

    Arguments:
        phrase (Str): user utterance
        recurrence_dict (Dict): map of strings to recurrence patterns

    Returns:
        Set: days as integers
    """
    recur = set()
    for r in recurrence_dict:
        if r in phrase:
            for day in recurrence_dict[r].split():
                recur.add(day)
    return recur


def create_recurring_rule(when, recur):
    """Create a recurring iCal rrule.

    Arguments:
        when (datetime): datetime object of alarm
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


def describe_recurrence(recur, recurrence_dict, connective="and"):
    """Create a textual description of the recur set.

    Arguments:
        recur (Set): recurrence pattern as set of day indices eg Set(["1","3"])
        recurrence_dict (Dict): map of strings to recurrence patterns
        connective (Str): word to connect list of days, default "and"

    Returns:
        Str: List of days as a human understandable string
    """
    day_list = list(recur)
    day_list.sort()
    days = " ".join(day_list)
    for r in recurrence_dict:
        if recurrence_dict[r] == days:
            return r  # accept the first perfect match

    # Assemble a long desc, e.g. "Monday and Wednesday"
    day_names = []
    for day in days.split(" "):
        for r in recurrence_dict:
            if recurrence_dict[r] == day:
                day_names.append(r)
                break

    return join_list(day_names, connective)
