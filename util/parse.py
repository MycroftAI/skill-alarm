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

from mycroft.util.parse import fuzzy_match as mycroft_fuzzy_match

def fuzzy_match(word, phrase, threshold):
    """
    Search a phrase to another phrase using fuzzy_match. Matches on a
    per word basis, and will not match if word is a subword.
    Args:
        word (str): string to be searched on a phrase
        phrase (str): string to be matched against the word
        threshold (int): minimum fuzzy matching score to be considered
                            a match
    Returns:
        (boolean): True if word is found in phrase. False if not.
    """
    matched = False
    score = 0
    phrase_split = phrase.split(" ")
    word_split_len = len(word.split(" "))

    for i in range(len(phrase_split) - word_split_len, -1, -1):
        phrase_comp = " ".join(phrase_split[i : i + word_split_len])
        score_curr = mycroft_fuzzy_match(phrase_comp, word.lower())

        if score_curr > score and score_curr >= threshold:
            score = score_curr
            matched = True

    return matched

def utterance_has_midnight(utterance, init_time, threshold, midnight_voc=None):
    """Check the time and see if it is midnight. 
    
    This is to check if the user said a recurring alarm with only the Day or
    if the user did specify to set an alarm on midnight. 

    Arguments:
        utterance (Str): utterance from user
        init_time (datetime): datetime extracted from utterance
        threshold (Float): fuzzy matching threshold
        midnight_voc (List): translated list of vocab equivalent to 'midnight'
    Returns:
        Bool: True if user requested an alarm be set for midnight
    """
    # TODO extract_datetime from utterance rather than passing it in
    if midnight_voc is None:
        midnight_voc = ["midnight"]
    matched = False
    if init_time is None:
        return matched
    if init_time.time() == datetime(1970, 1, 1, 0, 0, 0).time():
        for word in midnight_voc:
            matched = fuzzy_match(word, utterance, threshold)
            if matched:
                return matched

    return matched