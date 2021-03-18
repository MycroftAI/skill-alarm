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

import pytest
import unittest
from datetime import datetime

from lingua_franca import set_default_lang
from mycroft.util.parse import extract_datetime
from mycroft.util.time import now_local

from ..recur import create_day_set, create_recurring_rule, describe_recurrence

set_default_lang("en-us")

# A limited dictionary for testing purposes.
RECURRENCE_DICT = {
    "mondays": "1",
    "tuesdays": "2",
    "wednesdays": "3",
    "thursdays": "4",
    "fridays": "5",
    "saturdays": "6",
    "sundays": "0",
    "weekdays": "1 2 3 4 5",
}


class TestCreateDaySet(unittest.TestCase):
    def test_create_day_set(self):
        single_day_set = create_day_set("7pm on mondays", RECURRENCE_DICT)
        self.assertEqual(single_day_set, set("1"))
        week_day_set = create_day_set("4am on weekdays", RECURRENCE_DICT)
        self.assertEqual(week_day_set, set(["1", "2", "3", "4", "5"]))
        split_day_set = create_day_set("tuesdays and thursdays", RECURRENCE_DICT)
        self.assertEqual(split_day_set, set(["2", "4"]))


class TestCreateRecurringRule(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.RRULE_DAILY = "FREQ=WEEKLY;INTERVAL=1;BYDAY=SU,SA,WE,MO,FR,TH,TU"
        self.RRULE_MONDAYS = "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO"
        self.RRULE_WEEKDAYS = "FREQ=WEEKLY;INTERVAL=1;BYDAY=WE,MO,FR,TH,TU"

    def test_create_recurring_rule(self):
        rrule = create_recurring_rule(extract_datetime("last monday")[0], set("1"))
        self.assertEqual(
            rrule,
            {
                "timestamp": extract_datetime("monday")[0].timestamp(),
                "repeat_rule": self.RRULE_MONDAYS,
            },
        )


class TestDescribeRecurrence(unittest.TestCase):
    def test_create_describe_recurrence(self):
        recur_mon_wed = set(["1", "3"])
        description = describe_recurrence(recur_mon_wed, RECURRENCE_DICT)
        self.assertEqual(description, "mondays and wednesdays")
