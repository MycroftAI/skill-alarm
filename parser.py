from difflib import SequenceMatcher
import re
from abc import ABCMeta, abstractmethod
from datetime import datetime

from enum import Enum, unique

@unique
class TimeType(Enum):
    SEC = 1
    MIN = SEC * 60
    HR = MIN * 60
    DAY = HR * 24

    def to_sec(self, amount):
        return amount * self.value

    def from_sec(self, num_sec):
        return num_sec / self.value


class MycroftParser(metaclass=ABCMeta):
    """Helper class to parse common parameters like duration out of strings"""
    def __init__(self):
        pass

    @abstractmethod
    def format_quantities(self, quantities):
        """
        Arranges list of tuples of (ttype, amount) into language
        [(MIN, 12), (SEC, 3)] -> '12 minutes and three seconds'
        Args:
            quantities(list<tuple<TimeType, int>>):

        Returns:
            str: quantities in natural language
        """
        pass

    @abstractmethod
    def duration(self, string):
        """
        Raises: ValueError, if nothing found

        Returns:
            tuple<float, float>: duration in natural language string in seconds, confidence [0, 1]
        """
        pass

    @abstractmethod
    def to_number(self, string):
        """
        Converts word numbers to digit numbers
        Example: 'fifty 3 lemons and 2 hundred carrots' -> '53 lemons and '

        Returns:
            tuple<float, float>: converted number, confidence [0, 1]
        """
        pass

    def duration_to_str(self, dur):
        """
        Converts duration in seconds to appropriate time format in natural langauge
        70 -> '1 minute and 10 seconds'
        """
        quantities = []
        left_amount = dur
        for ttype in reversed(list(TimeType)):
            amount = ttype.from_sec(left_amount)
            int_amount = int(amount + 0.000000001)
            left_amount = ttype.to_sec(amount - int_amount)
            if int_amount > 0:
                quantities.append((ttype, int_amount))
        return self.format_quantities(quantities)


class Parser(MycroftParser):
    """Helper class to parse common parameters like duration out of strings"""

    def __init__(self):
        self.units = [
            ('one', '1'),
            ('two', '2'),
            ('three', '3'),
            ('four', '4'),
            ('five', '5'),
            ('size', '6'),
            ('seven', '7'),
            ('eight', '8'),
            ('nine', '9'),
            ('ten', '10'),
            ('eleven', '11'),
            ('twelve', '12'),
            ('thir', '3.'),
            ('for', '4.'),
            ('fif', '5.'),
            ('teen', '+10'),
            ('ty', '*10'),
            ('hundred', '* 100'),
            ('thousand', '* 1000'),
            ('million', '* 1000000'),
            ('and', '_+_')
        ]
        self.ttype_names_s = {
            TimeType.SEC: ['second', 'sec', 's'],
            TimeType.MIN: ['minute', 'min', 'm'],
            TimeType.HR: ['hour', 'hr', 'h'],
            TimeType.DAY: ['day', 'dy', 'd']
        }

        self.day_numbers = {
            'today': 0,
            'tomorrow': 1,
        }
        self.week_days = {
            'monday',
            'tuesday',
            'wednesday',
            'thursday',
            'friday',
            'saturday',
            'sunday'
        }

        units = [
            "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
            "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
            "sixteen", "seventeen", "eighteen", "nineteen",
        ]

        tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
                "ninety"]

        scales = ["hundred", "thousand", "million", "billion", "trillion"]

        self.numwords = {}
        self.numwords["and"] = (1, 0)
        for idx, word in enumerate(units):
            self.numwords[word] = (1, idx)
        for idx, word in enumerate(tens):
            self.numwords[word] = (1, idx * 10)
        for idx, word in enumerate(scales):
            self.numwords[word] = (10 ** (idx * 3 or 2), 0)

    def duration(self, string):
        regex_str = ('(((' + '|'.join(k for k, v in self.units) + r'|[0-9])+[ \-\t]*)+)(' +
                     '|'.join(name for ttype, names in self.ttype_names_s.items() for name in
                              names) + ')s?')
        dur = 0
        matches = tuple(re.finditer(regex_str, string))
        if len(matches) == 0:
            raise ValueError
        for m in matches:
            num_str = m.group(1)
            ttype_str = m.group(4)
            for ttype, names in self.ttype_names_s.items():
                if ttype_str in names:
                    ttype_typ = ttype
            num, conf = self.to_number(num_str)
            dur += ttype_typ.to_sec(num)
        return dur, conf

    def time(self, time_str):
        morning, evening = False, False
        if 'pm' in time_str.lower():
            evening = True
        m = re.search('[0-9]{1,2}:[0-9]{2}', time_str)
        if m:
            match = m.group(0)
            hour, minute = match.split(':')
        else:
            m = re.search('[0-9]{1,2}', time_str)
            if m:
                match = m.group(0)
                hour, minute = match, '0'
            else:
                raise ValueError
        hour, minute = int(hour), int(minute)
        if evening:
            hour += 12

        time_str = time_str.replace(match, '')
        now = datetime.now()
        return time_str, datetime(now.year, now.month, now.day, hour, minute)

    def days(self, time_str):
        for day in self.day_numbers:
            if day in time_str:
                day = self.day_numbers[day] + datetime.today().day
                return time_str.replace(day, ''), datetime(0, 0, day)

        now = datetime.now()
        yr, mo = now.year, now.month
        for day in self.week_days:
            if day in time_str:
                today = datetime.today().weekday()
                duration = self.week_days.index(day) - today
                if duration < 0:
                    duration += len(self.week_days)
                day = datetime.today().day + duration
                return time_str.replace(day, ''), datetime(yr, mo, day)
        return time_str, datetime(yr, mo, datetime.today().day)

    def date(self, time_str):
        time_str, day = self.days(time_str)
        time_str, time = self.time(time_str)
        t = datetime.now()
        t = datetime(t.year, t.month, day.day, time.hour, time.minute)
        return time_str, t

    def to_number(self, textnum):

        ordinal_words = {'first': 1, 'second': 2, 'third': 3, 'fifth': 5, 'eighth': 8,
                         'ninth': 9, 'twelfth': 12}
        ordinal_endings = [('ieth', 'y'), ('th', '')]

        textnum = textnum.replace('-', ' ')

        current = result = 0
        curstring = ""
        onnumber = False
        for word in textnum.split():
            if word in ordinal_words:
                scale, increment = (1, ordinal_words[word])
                current = current * scale + increment
                if scale > 100:
                    result += current
                    current = 0
                onnumber = True
            else:
                for ending, replacement in ordinal_endings:
                    if word.endswith(ending):
                        word = "%s%s" % (word[:-len(ending)], replacement)
                try:
                    num = float(word)
                    if num % 1 == 0:
                        num = int(num)
                except ValueError:
                    num = None

                if word not in self.numwords and num is None:
                    if onnumber:
                        curstring += repr(result + current) + " "
                    curstring += word + " "
                    result = current = 0
                    onnumber = False
                else:
                    if num is not None:
                        scale, increment = 1, num
                    else:
                        scale, increment = self.numwords[word]

                    current = current * scale + increment
                    if scale > 100:
                        result += current
                        current = 0
                    onnumber = True
            if onnumber:
                curstring += repr(result + current)
            return curstring

    def to_number(self, string):
        string = string.replace('-', ' ')  # forty-two -> forty two
        for unit, value in self.units:
            string = string.replace(unit, value)
        string = re.sub(r'([0-9]+)[ \t]*([\-+*/])[ \t]*([0-9+])', r'\1\2\3', string)

        regex_re = [
            (r'[0-9]+\.([^\-+*/])', r'a\1'),
            (r'\.([\-+*/])', r'\1'),
            (r' \* ', r'*'),
            (r' _\+_ ', r'+'),
            (r'([^0-9])\+[0-9]+', r'\1'),
            (r'([0-9]) ([0-9])', r'\1+\2'),
            (r'(^|[^0-9])[ \t]*[\-+*/][ \t]*', ''),
            (r'[ \t]*[\-+*/][ \t]*([^0-9]|$)', '')
        ]

        for sr, replace in regex_re:
            string = re.sub(sr, replace, string)

        num_strs = re.findall(r'[0-9\-+*/]+', string)
        if len(num_strs) == 0:
            raise ValueError

        num_str = max(num_strs, key=len)

        conf = SequenceMatcher(None, string.replace(' ', ''), num_str.replace(' ', '')).ratio()

        try:
            # WARNING Eval is evil; always filter string to only numbers and operators
            return eval(num_str), conf
        except SyntaxError:
            raise ValueError

    def format_quantities(self, quantities):
        complete_str = ', '.join(
            [str(amount) + ' ' + self.ttype_names_s[ttype][0] + ('s' if amount > 1 else '') for
             ttype, amount in quantities])
        complete_str = ' and '.join(complete_str.rsplit(', ', 1))
        return complete_str
