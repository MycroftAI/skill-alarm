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

from .alarm import (
    alarm_log_dump,
    curate_alarms,
    get_alarm_local,
    get_next_repeat,
    has_expired_alarm,
)
from mycroft.util.format import nice_relative_time
from .parse import fuzzy_match, utterance_has_midnight
from .recur import create_day_set, create_recurring_rule, describe_recurrence