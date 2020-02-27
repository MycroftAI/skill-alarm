Feature: Alarm skill functionality

  Scenario Outline: user sets an alarm for a time
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<set alarm for a 8 am>"
     Then "skill-alarm" should reply with dialog from "alarm.scheduled.for.time.dialog"

  Examples: user sets an alarm for a time
    | set alarm for 8 am |
    | set an alarm for 7:30 am |
    | create an alarm for 7:30 am |
    | start an alarm for &:30 am |
    | alarm 6 pm |
    | alarm for 8 tonight |
    | let me know when it's 8:30 pm |
    | wake me up at 7 tomorrow morning |

  Scenario Outline: user sets an alarm without saying a time
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<set alarm>"
     Then "skill-alarm" should reply with dialog from "query.for.when.dialog"
     And the user replies "8:00 am"
     And "skill-alarm" should reply with dialog from "alarm.scheduled.for.time.dialog"

  Examples: set alarm withot saying a time
    | set alarm |
    | set an alarm for tomorrow morning |
    | wake me up tomorrow |
    | alarm tonight |
    | alarm |
    | set an alarm |
    | create an alarm |

  Scenario Outline: user sets an alarm with a name with a time
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<set an alarm named sandwich for 12 pm>"
     Then "skill-alarm" should reply with dialog from "alarm.scheduled.for.time.dialog"

  Examples: user sets an alarm with a name with a time
    | set an alarm named sandwich for 12 pm |
    | set an alarm for 10 am for stretching |
    | set an alarm for stretching 10 am |
    | set an alarm named brunch for 11 am |
    | set an alarm called brunch for 11 am |
    | set an alarm named workout for 11 am |

  Scenario Outline: user sets an alarm without specifiying am or pm
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<set an alarm for 6:30>"
     Then "skill-alarm" should reply with dialog from "alarm.scheduled.for.time.dialog"

  Examples: user sets an alarm without specifiying am or pm
    | set an alarm for 6:30 |
    | set an alarm for 7 |
    | alarm for 12 |
    | wake me up at 6:30 |
    | let me know when it's 6 |

  Scenario Outline: set an alarm for a duration instead of a time
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<set an alarm for 30 minutes>"
     Then "skill-alarm" should reply with dialog from "alarm.scheduled.for.time.dialog"

  Examples:
    | set an alarm for 30 minutes |
    | alarm in 5 minutes |
    | alarm in 5 imnutes and 30 seconds |
    | set an alarm 8 hours from now |
    | set an alarm 8 hours and 30 minutes from now |

  Scenario Outline: user sets a named alarm without saying a time
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<set an alarm for sandwich>"
     Then "skill-alarm" should reply with dialog from "query.for.when.dialog"
     And the user replies "8 am"
     And "skill-alarm" should reply with dialog from "alarm.scheduled.for.time.dialog"

  Examples: set a named alarm without saying a time
    | set a an alarm for sandwich |
    | set an alarm for stretching |
    | set an alarm named meeting |

  Scenario Outline: user sets a recurring alarm
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<set alarm every weekday at 7:30 am>"
     Then "skill-alarm" should reply with dialog from "recurring.alarm.scheduled.for.time.dialog"

  Examples: set a recurring alarm
    | set alarm every weekday at 7:30 am |
    | alarm every weekday at 7:30 am |
    | wake me up every weekday at 7:30 am |
    | wake me up every day at 7:30 am except on the weekends |
    | set an alarm every wednesday at 11 am |
    | set an alarm for weekends at 3 pm |
    | set an alarm for 3 pm every weekend |

  Scenario Outline: user sets a recurring alarm without saying a time
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<set a recurring alarm for mondays>"
     Then "skill-alarm" should reply with dialog from "query.for.when.dialog"
     And the user says "<8 am>"
     And "skill-alarm" should reply with dialog from "alarm.scheduled.for.time.dialog"

  Examples: set a recuring alarm without saying a time
    | set a recurring alarm for mondays |
    | set a recurring alarm for tuesday |
    | create a repeating alarm for weekdays |
    | set a recurring alarm for weekends |

  Scenario Outline: user sets a recurring alarm without saying a day
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<set a recurring alarm for 8 am>"
     Then "skill-alarm" should reply with dialog from "query.recurrence.dialog"
     And the user says "<weekdays>"
     And "skill-alarm" should reply with dialog from "alarm.scheduled.for.time.dialog"

    | set a recurring alarm for 8 am | weekdays |
    | set a recurring alarm for 12 pm | tuesday |
    | create a repeating alarm for 10 pm | monday |

  Scenario Outline: user sets recurring named alarm
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<set a recurring alarm named lunch for 1 pm>"
     Then "skill-alarm" should reply with dialog from "query.recurrence.dialog"
     And the user says "<every day>"
     And "skill-alarm" should reply with dialog from "alarm.scheduled.for.time.dialog"

   | set a recurring alarm named lunch for 1 pm | every day |
   | set a recurring alarm named wake up for 8 am | weekdays |
   | set a recurring alarm for 12 pm | tuesday |
   | create a repeating alarm for 10 pm | monday |

  Scenario Outline: user asks for alarm status of a single alarm
    Given an english speaking user
    And there are no previous alarms set
    And an alarm is set for 9:00 am on weekdays
    When the user says "<alarm status>"
    Then "skill-alarm" should reply with dialog from "alarms.list.single.dialog"

  Examples: status of a single alarm
    | alarm status |
    | do I have any alarms |
    | what alarms do I have |
    | are there any alarms set |
    | is there an alarm set |
    | what time is my alarm set to |
    | show me my alarms |
    | tell me my alarms |
    | when will my alarm go off |
    | when's my alarm |

  Scenario Outline: user asks for alarm status of multiple alarms
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is set for 9:00 am on weekdays
     And an alarm is set for 6:00 pm on wednesday
     When the user says "<alarm status>"
     Then "skill-alarm" should reply with dialog from "alarms.list.multi.dialog"

  Examples: status of multiple alarms
    | alarm status |
    | do I have any alarms |
    | what alarms do I have |
    | are there any alarms set |
    | is there an alarm set |
    | what time is my alarm set to |
    | tell me my alarms |
    | show me my alarms |
    | when will my alarm go off |
    | when's my alarm |

  Scenario Outline: user asks for alarm status when no alarms are sets
    Given an english speaking user
     And there are no previous alarms set
     When the user says "<alarm status>"
     Then "skill-alarm" should reply with dialog from "alarms.list.empty.dialog"

  Examples: status when no alarms are set
     | alarm status |
     | do I have any alarms |
     | what alarms do I have |
     | are there any alarms set |
     | is there an alarm set |
     | what time is my alarm set to |
     | tell me my alarms |
     | show me my alarms |
     | when will my alarm go off |
     | when's my alarm |

  Scenario Outline: user stops an expired alarm when beeping
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is expired and beeping
     When the user says "<stop>"
     Then "skill-alarm" should stop beeping

  Examples: stop beeping
    | stop |
    | stop alarm |
    | disable alarm |
    | cancel |
    | cancel alarm |
    | turn it off |
    | turn off |
    | turn off alarm |
    | silence |
    | abort |
    | kill alarm |

  Scenario Outline: user snoozes a beeping alarm
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is expired and beeping
     When the user says "<snooze>"
     Then "skill-alarm" should stop beeping and start beeping again 10 minutes

  Examples: snooze a beeping alarm
    | snooze |
    | snooze alarm |
    | not yet |
    | 10 more minutes |
    | 10 minutes |
    | snooze for 10 minutes |
    | give me 10 minutes |
    | wake me up in 10 minutes |
    | remind me in 10 minutes |
    | let me sleep |

  Scenario Outline: user snoozes an beeping alarm for a specific time
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is expired and beeping
     When the user says "<snooze for 5 minutes>"
     Then "skill-alarm" should stop beeping and start beeping again 5 minutes

  Examples: snooze a beeping alarm for a specific time
    | snooze for 5 minutes |
    | give me 10 minutes |

  Scenario Outline: user deletes an alarm when a single alarm is active
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is set for 9:00 am on monday
     When the user says "<delete alarm>"
     Then "skill-alarm" should reply with dialog from "ask.cancel.desc.alarm.dialog"
     And the user says "yes"
     And "skill-alarm" should reply with dialog from "alarm.cancelled.desc.dialog"

  Examples: delete an alarm when a single alarm is active
    | delete alarm |
    | cancel alarm |
    | disable alarm |
    | turn off alarm |
    | stop alarm |
    | abort alarm |
    | remove alarm |

  Scenario Outline: user deletes an alarm when multiple alarms are active
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is set for 9:00 am on monday
     And an alarm is set for 10:00 pm on friday
     When the user says "<delete alarm>"
     Then "skill-alarm" should reply with dialog from "ask.which.alarm.delete.dialog"
     And the user says "9:00 am"
     And "skill-alarm" should reply with dialog from "ask.cancel.desc.alarm.dialog"
     And the user says "yes"
     And "skill-alarm" should reply with dialog from "alarm.cancelled.desc.dialog"

  Examples: delete an alarm when multiple alarm are active
    | delete alarm |
    | cancel alarm |
    | disable alarm |
    | turn off alarm |
    | stop alarm |
    | abort alarm |
    | remove alarm |

  Scenario Outline: user deletes a specific alarm
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is set for 9:00 am on monday
     And an alarm is set for 10:00 pm on friday
     When the user says "<delete 9:00 am alarm>"
     And "skill-alarm" should reply with dialog from "ask.cancel.desc.alarm.dialog"
     And the user says "yes"
     And "skill-alarm" should reply with dialog from "alarm.cancelled.desc.dialog"

  Examples: delete an alarm when multiple alarm are active
    | delete 9:00 am alarm |
    | cancel 9:00 am alarm |
    | disable 9:00 am alarm |
    | turn off 9:00 am alarm |
    | stop 9:00 am alarm |
    | abort 9:00 am alarm |
    | remove 9:00 am alarm |

  Scenario Outline: user deletes all alarms
    Given an english speaking user
     And there are no previous alarms set
     And an alarm is set for 9:00 am on monday
     And an alarm is set for 10:00 pm on friday
     When the user says "<delete all alarms>"
     Then "skill-alarm" should reply with dialog from "ask.cancel.alarm.plural.dialog"
     And the user says "yes"
     And "skill-alarm" should reply with dialog from "alarm.cancelled.multi.dialog"

  Examples: delete an alarm when multiple alarm are active
    | delete all alarms |
    | cancel all alarms |
    | remove all alarms |
    | turn off all alarms |
    | stop all alarms |
    | abort all alarms |
    | remove all alarms |
    | remove every alarm |
    | delete every alarm |
